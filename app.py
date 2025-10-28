# stockly-backend/app.py
import os
import bcrypt
import pandas as pd
import numpy as np
import joblib
from datetime import datetime, timedelta

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, get_jwt
)
import mysql.connector
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
app.config['JWT_SECRET_KEY'] = (
    'd2f93bf403766b67b1cf7dc668a06f1229cc12c60929a5cafb215f23a596baa0'
)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

jwt = JWTManager(app)

# ----------------------------------------------------------------------
# DB helper
# ----------------------------------------------------------------------
def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='stockly_db'
    )

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
def log_action(user_id, username, action, details=None):
    if user_id is None:
        print("Logging warning: user_id is None — skipping log.")
        return
    username = username or ''
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = ("INSERT INTO `logs` (`user_id`, `username`, `action`, `details`) "
               "VALUES (%s, %s, %s, %s)")
        cursor.execute(sql, (user_id, username, action, details))
        conn.commit()
    except Exception as e:
        print("Logging error:", e)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ----------------------------------------------------------------------
# Load RF model (once at start-up)
# ----------------------------------------------------------------------
rf_model = joblib.load('rf_model.pkl')
feature_columns = joblib.load('rf_feature_columns.pkl')

# ----------------------------------------------------------------------
# File upload helpers
# ----------------------------------------------------------------------
ALLOWED_EXTENSIONS = {'xlsx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------
@app.route('/')
def home():
    return "Stockly API is running"

# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------
@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        if not username or not password:
            return jsonify({'error': 'Missing username or password'}), 400

        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, username, password, role FROM users WHERE username = %s",
            (username,)
        )
        user = cur.fetchone()
        conn.close()

        if not user or not bcrypt.checkpw(password.encode('utf-8'),
                                          user['password'].encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401

        token = create_access_token(
            identity=username,
            additional_claims={'role': user['role'], 'id': user['id']},
            expires_delta=timedelta(minutes=30)
        )
        log_action(user['id'], username, 'login',
                   f"User {username} logged in")
        return jsonify({
            'token': token,
            'role': user['role'],
            'id': user['id'],
            'username': user['username']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/register', methods=['POST'])
@jwt_required()
def register():
    claims = get_jwt()
    if claims.get('role') != 'manager':
        return jsonify({'error': 'Access denied: Managers only'}), 403

    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'employee')
    if not username or not password:
        return jsonify({'error': 'Missing username or password'}), 400
    if role not in ['manager', 'employee']:
        return jsonify({'error': 'Invalid role'}), 400

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
            (username, hashed, role)
        )
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        log_action(claims['id'], get_jwt_identity(),
                   'register_user', f"Registered {username} as {role}")
        return jsonify({'message': 'User created successfully'})
    except mysql.connector.Error as e:
        if e.errno == 1062:
            return jsonify({'error': 'Username already exists'}), 400
        return jsonify({'error': str(e)}), 500

# ----------------------------------------------------------------------
# Helper – upsert into sales_history
# ----------------------------------------------------------------------
def upsert_sales_history(item_id, code, month, year, qty_sold, rank=0):
    """Insert or update monthly aggregate in sales_history."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """SELECT id, quantity_sold FROM sales_history
               WHERE item_id = %s AND month = %s AND year = %s""",
            (item_id, month, year)
        )
        row = cur.fetchone()
        if row:
            new_qty = row[1] + qty_sold
            cur.execute(
                """UPDATE sales_history SET quantity_sold = %s, record_date = CURDATE()
                   WHERE id = %s""",
                (new_qty, row[0])
            )
        else:
            cur.execute(
                """INSERT INTO sales_history
                   (item_id, month, year, quantity_sold, rank, code, record_date)
                   VALUES (%s, %s, %s, %s, %s, %s, CURDATE())""",
                (item_id, month, year, qty_sold, rank, code)
            )
        conn.commit()
    finally:
        cur.close()
        conn.close()

# ----------------------------------------------------------------------
# Predict reorder (RF + DB)
# ----------------------------------------------------------------------
@app.route('/predict_reorder', methods=['POST'])
@jwt_required()
def predict_reorder():
    claims = get_jwt()
    username = get_jwt_identity()

    try:
        data = request.get_json()
        product_name = data.get('product_name')
        month = data.get('month')               # optional
        type_val = data.get('type')
        department_val = data.get('department')

        # ----- next month if none supplied -----
        now = datetime.now()
        if not month:
            month = (now.month % 12) + 1
            year = now.year + (1 if now.month == 12 else 0)
        else:
            year = now.year

        # ----- item lookup -----
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT item_id, item_code FROM items WHERE item_name = %s",
            (product_name,)
        )
        item = cur.fetchone()
        if not item:
            conn.close()
            return jsonify({'error': f"Item '{product_name}' not found"}), 404
        item_id = item['item_id']
        code = item['item_code']

        # ----- historical monthly sales (join items for type/department) -----
        cur.execute("""
            SELECT sh.rank, sh.code, sh.month, sh.year,
                   sh.quantity_sold AS quantity,
                   i.type, i.department
            FROM sales_history sh
            JOIN items i ON sh.item_id = i.item_id
            WHERE sh.item_id = %s
            ORDER BY sh.year, sh.month
        """, (item_id,))
        hist = cur.fetchall()
        conn.close()

        if not hist:
            return jsonify({'error': 'No historical sales data for this item'}), 404

        df = pd.DataFrame(hist)
        df['ITEM NAME'] = product_name
        df = df.sort_values(['year', 'month'])

        # ----- feature engineering (exact replica of notebook) -----
        df['item_avg_qty'] = df.groupby('ITEM NAME')['quantity'].transform('mean')
        df['item_std_qty'] = df.groupby('ITEM NAME')['quantity'].transform('std')
        df['prev_month_qty'] = df.groupby('ITEM NAME')['quantity'].shift(1).fillna(0)
        df['rolling_3m_avg'] = (
            df.groupby('ITEM NAME')['quantity']
            .rolling(window=3, min_periods=1)
            .mean()
            .reset_index(0, drop=True)
        )
        df['qty_change_pct'] = (
            df.groupby('ITEM NAME')['quantity']
            .pct_change()
            .fillna(0)
            .replace([np.inf, -np.inf], 1e10)
        )

        # ----- row for the month we want to predict -----
        last = df.iloc[-1]
        new_row = {
            'rank': last['rank'],
            'code': code,
            'month': month,
            'year': year,
            'quantity': 0,
            'type': type_val,
            'department': department_val,
            'ITEM NAME': product_name,
            'item_avg_qty': df['item_avg_qty'].mean(),
            'item_std_qty': df['item_std_qty'].mean(),
            'prev_month_qty': last['quantity'],
            'rolling_3m_avg': df['rolling_3m_avg'].tail(3).mean(),
            'qty_change_pct': 0
        }
        df_new = pd.DataFrame([new_row])

        # ----- one-hot encode -----
        df_new = pd.get_dummies(df_new, columns=['type', 'department'], drop_first=True)

        # ----- align columns with training -----
        for col in feature_columns:
            if col not in df_new.columns:
                df_new[col] = 0
        X_new = df_new[feature_columns]

        # ----- predict -----
        pred = int(rf_model.predict(X_new)[0])

        log_action(claims['id'], username, 'predict_reorder',
                   f"{product_name} → {month}/{year}: {pred}")

        return jsonify({'predicted_reorder_quantity': pred})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------------------------------------------------------------
# Items
# ----------------------------------------------------------------------
@app.route('/items', methods=['GET'])
@jwt_required()
def get_items():
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT item_id, item_code, item_name, department, type,
                   reorder_level, reorder_quantity
            FROM items ORDER BY department, type, item_name
        """)
        items = cur.fetchall()
        conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/add_item', methods=['POST'])
@jwt_required()
def add_item():
    claims = get_jwt()
    if claims.get('role') != 'manager':
        return jsonify({'error': 'Access denied: Managers only'}), 403

    data = request.get_json()
    required = ['item_code', 'item_name', 'department', 'type']
    if not all(k in data for k in required):
        return jsonify({'error': 'Missing required fields'}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO items
            (item_code, item_name, department, type,
             reorder_level, reorder_quantity)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            data['item_code'],
            data['item_name'],
            data['department'],
            data['type'],
            data.get('reorder_level', 10),
            data.get('reorder_quantity', 50)
        ))
        conn.commit()
        conn.close()
        log_action(claims['id'], get_jwt_identity(), 'add_item',
                   f"{data['item_name']} ({data['item_code']})")
        return jsonify({'message': 'Item added successfully'}), 201
    except mysql.connector.Error as e:
        if e.errno == 1062:
            return jsonify({'error': 'Item code already exists'}), 400
        return jsonify({'error': str(e)}), 500

# ----------------------------------------------------------------------
# Inventory
# ----------------------------------------------------------------------
@app.route('/add_inventory', methods=['POST'])
@jwt_required()
def add_inventory():
    claims = get_jwt()
    if claims.get('role') != 'manager':
        return jsonify({'error': 'Access denied: Managers only'}), 403

    data = request.get_json()
    try:
        item_id = int(data['item_id'])
        qty = int(data['stock_quantity'])
    except (KeyError, ValueError):
        return jsonify({'error': 'Invalid item_id or stock_quantity'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT item_id FROM items WHERE item_id = %s", (item_id,))
    if not cur.fetchone():
        conn.close()
        return jsonify({'error': 'Item not found'}), 404

    cur.execute("""
        INSERT INTO inventory_batches
        (item_id, supplier, batch_number, stock_quantity,
         expire_date, restock_date, user_id)
        VALUES (%s, %s, %s, %s, %s, CURDATE(), %s)
    """, (
        item_id,
        data.get('supplier', 'Default'),
        data.get('batch_number', ''),
        qty,
        data.get('expire_date'),
        claims['id']
    ))
    conn.commit()
    conn.close()
    log_action(claims['id'], get_jwt_identity(), 'add_inventory',
               f"{qty} units → item_id {item_id}")
    return jsonify({'message': 'Inventory added successfully'})


@app.route('/inventory', methods=['GET'])
@jwt_required()
def get_inventory():
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT i.item_id, i.item_code AS product_code,
                   i.item_name AS product_name, i.department,
                   SUM(ib.stock_quantity) AS stock_quantity,
                   MIN(ib.expire_date) AS expire_date,
                   i.reorder_level
            FROM items i
            LEFT JOIN inventory_batches ib ON i.item_id = ib.item_id
            WHERE ib.stock_quantity > 0 AND ib.expire_date > CURDATE()
            GROUP BY i.item_id
            ORDER BY i.item_name
        """)
        items = cur.fetchall()
        conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------------------------------------------------------------
# Sales (single)
# ----------------------------------------------------------------------
@app.route('/add_sale', methods=['POST'])
@jwt_required()
def add_sale():
    claims = get_jwt()
    data = request.get_json()
    try:
        item_id = int(data['item_id'])
        qty = int(data['quantity_sold'])
    except (KeyError, ValueError):
        return jsonify({'error': 'Invalid payload'}), 400

    conn = get_db_connection()
    cur = conn.cursor()

    # ---- stock check ----
    cur.execute(
        "SELECT SUM(stock_quantity) FROM inventory_batches "
        "WHERE item_id = %s AND expire_date > CURDATE() AND stock_quantity > 0",
        (item_id,)
    )
    total = cur.fetchone()[0] or 0
    if total < qty:
        conn.close()
        return jsonify({'error': 'Insufficient stock'}), 400

    # ---- record sale ----
    cur.execute(
        "INSERT INTO sales_transactions (item_id, quantity_sold, sale_date, user_id) "
        "VALUES (%s, %s, CURDATE(), %s)",
        (item_id, qty, claims['id'])
    )

    # ---- deduct from batches (FIFO) ----
    cur.execute(
        "SELECT id, stock_quantity FROM inventory_batches "
        "WHERE item_id = %s AND expire_date > CURDATE() AND stock_quantity > 0 "
        "ORDER BY expire_date ASC",
        (item_id,)
    )
    batches = cur.fetchall()
    remaining = qty
    for batch_id, batch_stock in batches:
        deduct = min(remaining, batch_stock)
        cur.execute(
            "UPDATE inventory_batches SET stock_quantity = stock_quantity - %s "
            "WHERE id = %s",
            (deduct, batch_id)
        )
        remaining -= deduct
        if remaining == 0:
            break

    # ---- update sales_history (monthly aggregate) ----
    cur.execute("SELECT item_code FROM items WHERE item_id = %s", (item_id,))
    code = cur.fetchone()[0]
    month = datetime.now().month
    year = datetime.now().year
    upsert_sales_history(item_id, code, month, year, qty)

    conn.commit()
    conn.close()
    log_action(claims['id'], get_jwt_identity(), 'add_sale',
               f"{qty} units of item_id {item_id}")
    return jsonify({'message': 'Sale added successfully'})

# ----------------------------------------------------------------------
# Bulk sales upload
# ----------------------------------------------------------------------
@app.route('/bulk_sales_upload', methods=['POST'])
@jwt_required()
def bulk_sales_upload():
    claims = get_jwt()
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if not file.filename or not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file'}), 400

    path = os.path.join(app.config['UPLOAD_FOLDER'],
                        secure_filename(file.filename))
    file.save(path)

    try:
        df = pd.read_excel(path)
        required = ['item_id', 'quantity_sold']
        if not all(c in df.columns for c in required):
            raise ValueError('Missing required columns')

        conn = get_db_connection()
        cur = conn.cursor()

        # ---- fetch item codes once ----
        item_ids = tuple(df['item_id'].astype(int).unique())
        placeholders = ','.join(['%s'] * len(item_ids))
        cur.execute(f"SELECT item_id, item_code FROM items WHERE item_id IN ({placeholders})", item_ids)
        code_map = {row[0]: row[1] for row in cur.fetchall()}

        for _, row in df.iterrows():
            item_id = int(row['item_id'])
            qty = int(row['quantity_sold'])
            sale_date = pd.to_datetime(row.get('sale_date', datetime.now())).date()
            month, year = sale_date.month, sale_date.year

            # stock check
            cur.execute(
                "SELECT SUM(stock_quantity) FROM inventory_batches "
                "WHERE item_id = %s AND expire_date > CURDATE()",
                (item_id,)
            )
            if (cur.fetchone()[0] or 0) < qty:
                continue

            # record sale
            cur.execute(
                "INSERT INTO sales_transactions (item_id, quantity_sold, sale_date, user_id) "
                "VALUES (%s, %s, %s, %s)",
                (item_id, qty, sale_date, claims['id'])
            )

            # deduct batches (FIFO)
            cur.execute(
                "SELECT id, stock_quantity FROM inventory_batches "
                "WHERE item_id = %s AND expire_date > CURDATE() ORDER BY expire_date ASC",
                (item_id,)
            )
            batches = cur.fetchall()
            rem = qty
            for b_id, b_stock in batches:
                deduct = min(rem, b_stock)
                cur.execute(
                    "UPDATE inventory_batches SET stock_quantity = stock_quantity - %s WHERE id = %s",
                    (deduct, b_id)
                )
                rem -= deduct
                if rem == 0:
                    break

            # update monthly aggregate
            code = code_map.get(item_id, '')
            upsert_sales_history(item_id, code, month, year, qty)

        conn.commit()
        conn.close()
        os.remove(path)
        log_action(claims['id'], get_jwt_identity(), 'bulk_sales_upload',
                   f"Uploaded {file.filename}")
        return jsonify({'message': 'Bulk sales added successfully'})
    except Exception as e:
        if os.path.exists(path):
            os.remove(path)
        return jsonify({'error': str(e)}), 500

# ----------------------------------------------------------------------
# Sales chart data
# ----------------------------------------------------------------------
@app.route('/inventory_sales/<int:item_id>', methods=['GET'])
@jwt_required()
def get_inventory_sales(item_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT YEAR(sale_date) AS year, MONTH(sale_date) AS month,
                   SUM(quantity_sold) AS total_units_sold
            FROM sales_transactions
            WHERE item_id = %s
            GROUP BY year, month
            ORDER BY year DESC, month DESC
            LIMIT 12
        """, (item_id,))
        rows = cur.fetchall()
        conn.close()
        out = [{'name': f"{r['month']}/{r['year']}", 'quantity': r['total_units_sold']} for r in rows]
        return jsonify(out)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------------------------------------------------------------
# Near-expiry & dead-stock
# ----------------------------------------------------------------------
@app.route('/near_expiry', methods=['GET'])
@jwt_required()
def get_near_expiry():
    days = int(request.args.get('days', 30))
    include_past = request.args.get('include_past', '0') == '1'
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        filter_clause = ("ib.expire_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)"
                         if include_past else "ib.expire_date >= CURDATE()")
        cur.execute(f"""
            SELECT ib.*, i.item_name AS product_name, i.department, i.type,
                   DATEDIFF(ib.expire_date, CURDATE()) AS days_left,
                   (SELECT AVG(st.quantity_sold)
                    FROM sales_transactions st
                    WHERE st.item_id IN (SELECT item_id FROM items WHERE department = i.department)
                      AND st.quantity_sold > 0 LIMIT 1) AS top_seller_avg
            FROM inventory_batches ib
            JOIN items i ON ib.item_id = i.item_id
            WHERE {filter_clause}
              AND DATEDIFF(ib.expire_date, CURDATE()) <= %s
            ORDER BY ib.expire_date ASC
        """, (days,))
        items = cur.fetchall()
        conn.close()

        for itm in items:
            dl = itm['days_left']
            disc = 0
            if dl <= 7:   disc = 40
            elif dl <= 14: disc = 20
            elif dl <= 30: disc = 10
            else:         disc = 5
            if itm['stock_quantity'] > 50: disc += 10
            elif itm['stock_quantity'] > 20: disc += 5
            if any(p in itm['type'] for p in ['Frozen','Food','Personal Care','Beverages']):
                disc += 5
            itm['recommended_discount'] = min(95, disc)
            itm['bundling_suggestion'] = (
                f"Bundle with top-seller in {itm['department']} "
                f"(avg sales: {int(itm['top_seller_avg'])} units/mo)"
                if itm['top_seller_avg'] else "Bundle with high-demand items"
            )
            itm['loyalty_tip'] = "Offer extra loyalty points for purchase"
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/dead_stock', methods=['GET'])
@jwt_required()
def get_dead_stock():
    months = int(request.args.get('months_back', 3))
    low = int(request.args.get('low_sales_threshold', 50))
    high = int(request.args.get('high_stock_threshold', 20))
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT i.item_id, i.item_name, i.item_code AS product_code,
                   SUM(ib.stock_quantity) AS stock_quantity,
                   MIN(ib.expire_date) AS expire_date,
                   COALESCE(SUM(st.quantity_sold),0) AS recent_sales
            FROM items i
            LEFT JOIN inventory_batches ib ON i.item_id = ib.item_id
            LEFT JOIN sales_transactions st ON i.item_id = st.item_id
                 AND st.sale_date >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
            GROUP BY i.item_id
            HAVING stock_quantity > %s AND recent_sales < %s
            ORDER BY recent_sales ASC, stock_quantity DESC
        """, (months, high, low))
        items = cur.fetchall()
        conn.close()
        for itm in items:
            if itm['stock_quantity'] > 100:
                itm['recommendation'] = 'Recommend 30% discount to clear high stock'
            elif itm['recent_sales'] == 0:
                itm['recommendation'] = 'Obsolete: Consider removal or bundling with popular items'
            else:
                itm['recommendation'] = f'Recommend {int((low - itm["recent_sales"])*0.5)}% discount or bundle promotion'
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ----------------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True)