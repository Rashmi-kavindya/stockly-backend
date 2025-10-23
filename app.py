# stockly-backend/app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
import mysql.connector
from mysql.connector import Error
import pandas as pd
import joblib
import numpy as np
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import os
import bcrypt

app = Flask(__name__)
CORS(app)

# JWT Config
app.config['JWT_SECRET_KEY'] = 'd2f93bf403766b67b1cf7dc668a06f1229cc12c60929a5cafb215f23a596baa0'  # Secure key
app.config['UPLOAD_FOLDER'] = 'uploads'  # For Excel uploads
jwt = JWTManager(app)

# DB Connection
def get_db_connection():
    return mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='stockly_db'
    )

# Logging Function
def log_action(user_id, username, action, details=None):
    if user_id is None:
        print("Logging warning: user_id is None — skipping log.")
        return
    if username is None:
        username = ''
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        sql = "INSERT INTO `logs` (`user_id`, `username`, `action`, `details`) VALUES (%s, %s, %s, %s)"
        params = (user_id, username, action, details)
        cursor.execute(sql, params)
        conn.commit()
    except Exception as e:
        print("Logging error:", e)
        print("Logging attempt:", sql, params)
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# Load dataset for predict_reorder (unchanged)
df = pd.read_csv('sri_dataset.csv')
df.fillna(0, inplace=True)
xgb_model = joblib.load('stockly_xgb_model.pkl')
feature_columns = joblib.load('stockly_feature_columns.pkl')

ALLOWED_EXTENSIONS = {'xlsx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    return "Stockly API is running"

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'error': 'Missing username or password'}), 400

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id, username, password, role FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        conn.close()

        if not user or not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401

        additional_claims = {'role': user['role'], 'id': user['id']}
        access_token = create_access_token(identity=username, additional_claims=additional_claims, expires_delta=timedelta(minutes=30))
        
        log_action(user['id'], username, 'login', f"User {username} logged in")

        return jsonify({'token': access_token, 'role': user['role'], 'id': user['id'], 'username': user['username']})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/register', methods=['POST'])
@jwt_required()
def register():
    claims = get_jwt()
    current_username = get_jwt_identity()
    if claims.get('role') != 'manager':
        return jsonify({'error': 'Access denied: Managers only'}), 403

    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        role = data.get('role', 'employee')

        if not username or not password:
            return jsonify({'error': 'Missing username or password'}), 400

        if role not in ['manager', 'employee']:
            return jsonify({'error': 'Invalid role'}), 400

        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                       (username, hashed_pw, role))
        conn.commit()
        new_user_id = cursor.lastrowid
        conn.close()

        log_action(claims['id'], current_username, 'register_user', f"Registered {username} as {role}")

        return jsonify({'message': 'User created successfully'})

    except Error as e:
        if e.errno == 1062:
            return jsonify({'error': 'Username already exists'}), 400
        return jsonify({'error': str(e)}), 500

@app.route('/predict_reorder', methods=['POST'])
@jwt_required()
def predict_reorder():
    current_username = get_jwt_identity()
    claims = get_jwt()
    try:
        data = request.get_json()
        product_name = data.get('product_name')
        month = int(data.get('month'))
        type_val = data.get('type')
        department_val = data.get('department')

        df_item = df[df['ITEM NAME'] == product_name]
        if df_item.empty:
            return jsonify({'error': f"Item '{product_name}' not found"}), 404

        item_avg = df_item['QUANTITY'].mean()
        item_std = df_item['QUANTITY'].std()
        prev_qty = df_item.iloc[-1]['QUANTITY']
        rolling_3m = df_item['QUANTITY'].iloc[-3:].mean()
        qty_change_pct = df_item['QUANTITY'].pct_change().iloc[-1] if len(df_item) > 1 else 0
        rank = df_item.iloc[-1]['RANK']
        code = df_item.iloc[-1]['CODE']

        sample = {
            'RANK': [rank],
            'CODE': [code],
            'MONTH': [month],
            'item_avg_qty': [item_avg],
            'item_std_qty': [item_std],
            'prev_month_qty': [prev_qty],
            'rolling_3m_avg': [rolling_3m],
            'qty_change_pct': [qty_change_pct]
        }

        for col in feature_columns:
            if col.startswith('TYPE_'):
                sample[col] = [1 if col == f'TYPE_{type_val}' else 0]
            elif col.startswith('DEPARTMENT_'):
                sample[col] = [1 if col == f'DEPARTMENT_{department_val}' else 0]

        sample_df = pd.DataFrame(sample)
        sample_df = sample_df.reindex(columns=feature_columns, fill_value=0)

        pred_qty = int(round(xgb_model.predict(sample_df)[0]))

        log_action(claims['id'], current_username, 'predict_reorder', f"Predicted reorder for {product_name}: {pred_qty}")

        return jsonify({'predicted_reorder_quantity': pred_qty})

    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/items', methods=['GET'])
@jwt_required()
def get_items():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT item_id, item_code, item_name, department, type, reorder_level, reorder_quantity
            FROM items ORDER BY department, type, item_name
        """)
        items = cursor.fetchall()
        conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/add_item', methods=['POST'])
@jwt_required()
def add_item():
    claims = get_jwt()
    current_username = get_jwt_identity()
    if claims.get('role') != 'manager':
        return jsonify({'error': 'Access denied: Managers only'}), 403
    try:
        data = request.get_json()
        item_code = data['item_code']
        item_name = data['item_name']
        department = data['department']
        type_ = data['type']
        reorder_level = data.get('reorder_level', 10)
        reorder_quantity = data.get('reorder_quantity', 50)

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO items (item_code, item_name, department, type, reorder_level, reorder_quantity)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (item_code, item_name, department, type_, reorder_level, reorder_quantity))
        conn.commit()
        conn.close()

        log_action(claims['id'], current_username, 'add_item', f"Added item {item_name} ({item_code})")

        return jsonify({'message': 'Item added successfully'}), 201
    except Error as e:
        if e.errno == 1062:
            return jsonify({'error': 'Item code already exists'}), 400
        return jsonify({'error': str(e)}), 500

@app.route('/add_inventory', methods=['POST'])
@jwt_required()
def add_inventory():
    claims = get_jwt()
    current_username = get_jwt_identity()
    if claims.get('role') != 'manager':
        return jsonify({'error': 'Access denied: Managers only'}), 403
    try:
        data = request.get_json()
        item_id = data['item_id']
        stock_quantity = int(data['stock_quantity'])
        expire_date = data.get('expire_date')
        batch_number = data.get('batch_number', '')
        supplier = data.get('supplier', 'Default')
        user_id = claims['id']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT item_id FROM items WHERE item_id = %s", (item_id,))
        if not cursor.fetchone():
            conn.close()
            return jsonify({'error': 'Item not found'}), 404

        cursor.execute("""
            INSERT INTO inventory_batches (item_id, supplier, batch_number, stock_quantity, expire_date, restock_date, user_id)
            VALUES (%s, %s, %s, %s, %s, CURDATE(), %s)
        """, (item_id, supplier, batch_number, stock_quantity, expire_date, user_id))
        conn.commit()
        conn.close()

        log_action(user_id, current_username, 'add_inventory', f"Added {stock_quantity} units to item_id {item_id}")

        return jsonify({'message': 'Inventory added successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/inventory', methods=['GET'])
@jwt_required()
def get_inventory():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT i.item_id, i.item_code as product_code, i.item_name as product_name, i.department,
                   SUM(ib.stock_quantity) as stock_quantity,
                   MIN(ib.expire_date) as expire_date,
                   i.reorder_level
            FROM items i LEFT JOIN inventory_batches ib ON i.item_id = ib.item_id
            WHERE ib.stock_quantity > 0 AND ib.expire_date > CURDATE()
            GROUP BY i.item_id
            ORDER BY i.item_name
        """)
        items = cursor.fetchall()
        conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/add_sale', methods=['POST'])
@jwt_required()
def add_sale():
    claims = get_jwt()
    current_username = get_jwt_identity()
    try:
        data = request.get_json()
        item_id = data['item_id']
        quantity_sold = int(data['quantity_sold'])
        user_id = claims['id']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT SUM(stock_quantity) FROM inventory_batches WHERE item_id = %s AND expire_date > CURDATE() AND stock_quantity > 0", (item_id,))
        total_stock = cursor.fetchone()[0] or 0
        if total_stock < quantity_sold:
            conn.close()
            return jsonify({'error': 'Insufficient stock'}), 400

        cursor.execute("INSERT INTO sales_transactions (item_id, quantity_sold, sale_date, user_id) VALUES (%s, %s, CURDATE(), %s)", 
                       (item_id, quantity_sold, user_id))

        cursor.execute("""
            SELECT id, stock_quantity FROM inventory_batches 
            WHERE item_id = %s AND expire_date > CURDATE() AND stock_quantity > 0 
            ORDER BY expire_date ASC
        """, (item_id,))
        batches = cursor.fetchall()
        remaining = quantity_sold
        for batch in batches:
            batch_id, batch_stock = batch
            deduct = min(remaining, batch_stock)
            cursor.execute("UPDATE inventory_batches SET stock_quantity = stock_quantity - %s WHERE id = %s", (deduct, batch_id))
            remaining -= deduct
            if remaining == 0:
                break

        conn.commit()
        conn.close()

        log_action(user_id, current_username, 'add_sale', f"Added sale of {quantity_sold} units for item_id {item_id}")

        return jsonify({'message': 'Sale added successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/bulk_sales_upload', methods=['POST'])
@jwt_required()
def bulk_sales_upload():
    claims = get_jwt()
    current_username = get_jwt_identity()
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Invalid file type (must be .xlsx)'}), 400

    user_id = claims['id']
    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    try:
        df = pd.read_excel(file_path)
        if not all(col in df.columns for col in ['item_id', 'quantity_sold']):
            os.remove(file_path)
            return jsonify({'error': 'Excel must have columns: item_id, quantity_sold'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()
        for _, row in df.iterrows():
            item_id = int(row['item_id'])
            quantity_sold = int(row['quantity_sold'])
            sale_date = row.get('sale_date', datetime.now().date())

            cursor.execute("SELECT SUM(stock_quantity) FROM inventory_batches WHERE item_id = %s AND expire_date > CURDATE()", (item_id,))
            total_stock = cursor.fetchone()[0] or 0
            if total_stock < quantity_sold:
                continue

            cursor.execute("INSERT INTO sales_transactions (item_id, quantity_sold, sale_date, user_id) VALUES (%s, %s, %s, %s)", 
                           (item_id, quantity_sold, sale_date, user_id))

            cursor.execute("SELECT id, stock_quantity FROM inventory_batches WHERE item_id = %s AND expire_date > CURDATE() ORDER BY expire_date ASC", (item_id,))
            batches = cursor.fetchall()
            remaining = quantity_sold
            for batch in batches:
                batch_id, batch_stock = batch
                deduct = min(remaining, batch_stock)
                cursor.execute("UPDATE inventory_batches SET stock_quantity = stock_quantity - %s WHERE id = %s", (deduct, batch_id))
                remaining -= deduct
                if remaining == 0:
                    break

        conn.commit()
        conn.close()
        os.remove(file_path)

        log_action(user_id, current_username, 'bulk_sales_upload', f"Uploaded bulk sales from {filename}")

        return jsonify({'message': 'Bulk sales added successfully'})
    except Exception as e:
        os.remove(file_path)
        return jsonify({'error': str(e)}), 500

@app.route('/inventory_sales/<int:item_id>', methods=['GET'])
@jwt_required()
def get_inventory_sales(item_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT YEAR(sale_date) as year, MONTH(sale_date) as month, SUM(quantity_sold) as total_units_sold
            FROM sales_transactions
            WHERE item_id = %s
            GROUP BY year, month
            ORDER BY year DESC, month DESC
            LIMIT 12
        """, (item_id,))
        data = cursor.fetchall()
        conn.close()
        formatted = [{'name': f"{d['month']}/{d['year']}", 'quantity': d['total_units_sold']} for d in data]
        return jsonify(formatted)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/near_expiry', methods=['GET'])
@jwt_required()
def get_near_expiry():
    days_threshold = int(request.args.get('days', 30))
    include_past = request.args.get('include_past', '0') == '1'
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        date_filter = "ib.expire_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)" if include_past else "ib.expire_date >= CURDATE()"
        cursor.execute(f"""
            SELECT ib.*, i.item_name as product_name, i.department, i.type, 
                   DATEDIFF(ib.expire_date, CURDATE()) as days_left,
                   (SELECT AVG(st.quantity_sold) FROM sales_transactions st 
                    WHERE st.item_id IN (SELECT item_id FROM items WHERE department = i.department) 
                    AND st.quantity_sold > 0 LIMIT 1) as top_seller_avg
            FROM inventory_batches ib
            JOIN items i ON ib.item_id = i.item_id
            WHERE {date_filter} AND DATEDIFF(ib.expire_date, CURDATE()) <= %s
            ORDER BY ib.expire_date ASC
        """, (days_threshold,))
        items = cursor.fetchall()
        conn.close()

        for item in items:
            days_left = item['days_left']
            base_discount = 0
            if days_left <= 7:
                base_discount = 40
            elif days_left <= 14:
                base_discount = 20
            elif days_left <= 30:
                base_discount = 10
            else:
                base_discount = 5

            if item['stock_quantity'] > 50:
                base_discount += 10
            elif item['stock_quantity'] > 20:
                base_discount += 5

            perishables = ['Frozen', 'Food', 'Personal Care', 'Beverages']
            if any(p in item['type'] for p in perishables):
                base_discount += 5

            item['recommended_discount'] = min(95, base_discount)
            item['bundling_suggestion'] = (f"Bundle with top-seller in {item['department']} (avg sales: {int(item['top_seller_avg'])} units/mo)" 
                                          if item['top_seller_avg'] else "Bundle with high-demand items")
            item['loyalty_tip'] = "Offer extra loyalty points for purchase"

        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/dead_stock', methods=['GET'])
@jwt_required()
def get_dead_stock():
    try:
        months_back = int(request.args.get('months_back', 3))
        low_sales_threshold = int(request.args.get('low_sales_threshold', 50))
        high_stock_threshold = int(request.args.get('high_stock_threshold', 20))

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT i.item_id, i.item_name, i.item_code as product_code, 
                   SUM(ib.stock_quantity) as stock_quantity,
                   MIN(ib.expire_date) as expire_date,
                   COALESCE(SUM(st.quantity_sold), 0) as recent_sales
            FROM items i
            LEFT JOIN inventory_batches ib ON i.item_id = ib.item_id
            LEFT JOIN sales_transactions st ON i.item_id = st.item_id
                AND st.sale_date >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
            GROUP BY i.item_id
            HAVING stock_quantity > %s AND recent_sales < %s
            ORDER BY recent_sales ASC, stock_quantity DESC
        """, (months_back, high_stock_threshold, low_sales_threshold))
        dead_items = cursor.fetchall()
        conn.close()

        for item in dead_items:
            if item['stock_quantity'] > 100:
                item['recommendation'] = 'Recommend 30% discount to clear high stock'
            elif item['recent_sales'] == 0:
                item['recommendation'] = 'Obsolete: Consider removal or bundling with popular items'
            else:
                item['recommendation'] = f'Recommend {int((low_sales_threshold - item["recent_sales"]) * 0.5)}% discount or bundle promotion'

        return jsonify(dead_items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)