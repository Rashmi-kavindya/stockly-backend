# app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import pandas as pd
import numpy as np
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
import bcrypt

app = Flask(__name__)
CORS(app)

# JWT Config
app.config['JWT_SECRET_KEY'] = 'd2f93bf403766b67b1cf7dc668a06f1229cc12c60929a5cafb215f23a596baa0'  # Change this!
jwt = JWTManager(app)

# DB Connection
def get_db_connection():
    return mysql.connector.connect(
        host='localhost', user='root', password='',
        database='stockly_db'
    )

# Logging Function
def log_action(user_id, username, action, details=None):
    """
    Insert a row into logs. This version:
    - quotes column names
    - validates inputs
    - prints errors and query parameters for debugging
    - always closes cursor/connection
    """
    if user_id is None:
        print("Logging warning: user_id is None — skipping log.")
        return
    if username is None:
        username = ''  # avoid NOT NULL problems

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
        # print full diagnostic
        print("Logging error:", e)
        try:
            # debug: show what attempted to insert
            print("Logging attempt:", sql, params)
        except Exception:
            pass
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


# Load dataset (used for feature extraction) - for predict compat
df = pd.read_csv('sri_dataset.csv')  # your dataset path
df.fillna(0, inplace=True)

# Load trained model and feature columns
xgb_model = joblib.load('stockly_xgb_model.pkl')
feature_columns = joblib.load('stockly_feature_columns.pkl')

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
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        conn.close()

        if not user or not bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            return jsonify({'error': 'Invalid credentials'}), 401

        # Create JWT with role
        additional_claims = {'role': user['role']}
        access_token = create_access_token(identity=username, additional_claims=additional_claims)
        
        # Log the action
        log_action(user['id'], username, 'login', f"User {username} logged in")

        return jsonify({'token': access_token, 'role': user['role']})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/register', methods=['POST'])
@jwt_required()
def register():
    claims = get_jwt()  # Get claims for role
    current_username = get_jwt_identity()  # This is the username (string)
    if claims.get('role') != 'manager':
        return jsonify({'error': 'Access denied: Managers only'}), 403

    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        role = data.get('role', 'employee')  # Default to employee

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
        new_user_id = cursor.lastrowid  # Not used, but available
        conn.close()

        # Get current user_id for logging
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE username = %s", (current_username,))
        current_user = cursor.fetchone()
        conn.close()
        
        # Log the action
        log_action(current_user['id'], current_username, 'register_user', f"Registered {username} as {role}")

        return jsonify({'message': 'User created successfully'})

    except Error as e:
        if e.errno == 1062:  # Duplicate entry
            return jsonify({'error': 'Username already exists'}), 400
        return jsonify({'error': str(e)}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/predict_reorder', methods=['POST'])
@jwt_required()
def predict_reorder():
    current_username = get_jwt_identity()
    try:
        data = request.get_json()
        product_name = data.get('product_name')
        month = int(data.get('month'))
        type_val = data.get('type')
        department_val = data.get('department')

        # Filter dataset for the item
        df_item = df[df['ITEM NAME'] == product_name]
        if df_item.empty:
            return jsonify({'error': f"Item '{product_name}' not found"}), 404

        # Feature engineering
        item_avg = df_item['QUANTITY'].mean()
        item_std = df_item['QUANTITY'].std()
        prev_qty = df_item.iloc[-1]['QUANTITY']
        rolling_3m = df_item['QUANTITY'].iloc[-3:].mean()
        qty_change_pct = df_item['QUANTITY'].pct_change().iloc[-1] if len(df_item) > 1 else 0
        rank = df_item.iloc[-1]['RANK']
        code = df_item.iloc[-1]['CODE']

        # Prepare input dataframe
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

        # Add one-hot encoded TYPE and DEPARTMENT
        for col in feature_columns:
            if col.startswith('TYPE_'):
                sample[col] = [1 if col == f'TYPE_{type_val}' else 0]
            elif col.startswith('DEPARTMENT_'):
                sample[col] = [1 if col == f'DEPARTMENT_{department_val}' else 0]

        sample_df = pd.DataFrame(sample)
        sample_df = sample_df.reindex(columns=feature_columns, fill_value=0)

        # Predict (round to int for whole units)
        pred_qty = int(round(xgb_model.predict(sample_df)[0]))

        # Get current user_id for logging
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE username = %s", (current_username,))
        current_user = cursor.fetchone()
        conn.close()
        
        # Log the action
        log_action(current_user['id'], current_username, 'predict_reorder', f"Predicted reorder for {product_name}: {pred_qty}")

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
            SELECT item_id, item_code, item_name, department, type 
            FROM items ORDER BY department, type, item_name
        """)
        items = cursor.fetchall()
        conn.close()
        return jsonify(items)
    except Exception as e:
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
        product_code = data['product_code']
        stock_quantity = int(data['stock_quantity'])
        expire_date = data.get('expire_date')  # YYYY-MM-DD
        batch_number = data.get('batch_number', '')
        supplier = data.get('supplier', 'Default')

        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO inventory (product_code, product_name, supplier, batch_number, stock_quantity, expire_date, record_date)
            VALUES (%s, (SELECT item_name FROM items WHERE item_code = %s), %s, %s, %s, %s, CURDATE())
            ON DUPLICATE KEY UPDATE 
            stock_quantity = stock_quantity + %s, last_restock_date = CURDATE()
        """
        cursor.execute(query, (product_code, product_code, supplier, batch_number, stock_quantity, expire_date, stock_quantity))
        conn.commit()
        conn.close()

        # Get current user_id for logging
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE username = %s", (current_username,))
        current_user = cursor.fetchone()
        conn.close()
        
        # Log the action
        log_action(current_user['id'], current_username, 'add_inventory', f"Added {stock_quantity} to {product_code}")

        return jsonify({'message': 'Inventory updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/inventory', methods=['GET'])
@jwt_required()
def get_inventory():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM inventory WHERE stock_quantity > 0 ORDER BY expire_date ASC")
        items = cursor.fetchall()
        conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/inventory_sales/<int:item_id>', methods=['GET'])
@jwt_required()
def get_inventory_sales(item_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                MONTH(record_date) as month, 
                YEAR(record_date) as year, 
                SUM(units_sold) as total_units_sold
            FROM inventory 
            JOIN items ON inventory.product_code = items.item_code
            WHERE items.item_id = %s AND stock_quantity > 0  -- Exclude depleted batches
            GROUP BY year, month 
            ORDER BY year DESC, month DESC LIMIT 12
        """, (item_id,))
        data = cursor.fetchall()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/near_expiry', methods=['GET'])
@jwt_required()
def get_near_expiry():
    days_threshold = int(request.args.get('days', 30))
    include_past = request.args.get('include_past', '0') == '1'  # Optional param for past expiry
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Fixed: Added i.department to SELECT
        date_filter = "expire_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)" if include_past else "expire_date >= CURDATE()"
        cursor.execute(f"""
            SELECT inv.product_name, inv.stock_quantity, inv.expire_date,
                   i.type, i.department, DATEDIFF(expire_date, CURDATE()) as days_left,
                   (SELECT AVG(quantity_sold) FROM sales_history sh JOIN items it ON sh.item_id = it.item_id 
                    WHERE it.department = i.department AND sh.quantity_sold > 0 ORDER BY sh.quantity_sold DESC LIMIT 1) as top_seller_avg
            FROM inventory inv
            JOIN items i ON inv.product_code = i.item_code
            WHERE {date_filter} AND DATEDIFF(expire_date, CURDATE()) <= %s
            ORDER BY expire_date ASC
        """, (days_threshold,))
        items = cursor.fetchall()
        conn.close()
        
        # Custom Tiered Discount Logic (same as before)
        for item in items:
            days_left = item['days_left']
            base_discount = 0
            if days_left <= 7:
                base_discount = 70  # High urgency
            elif days_left <= 14:
                base_discount = 50
            elif days_left <= 30:
                base_discount = 30
            else:
                base_discount = 15  # Mild
            
            # Stock multiplier
            if item['stock_quantity'] > 50:
                base_discount += 20
            elif item['stock_quantity'] > 20:
                base_discount += 10
            
            # Type boost (perishables)
            perishables = ['Frozen', 'Food', 'Personal Care', 'Beverages']
            if any(p in item['type'] for p in perishables):
                base_discount += 10
            
            item['recommended_discount'] = min(95, base_discount)  # Cap at 95%
            
            # Bundling Rec (now uses department)
            if item['top_seller_avg']:
                item['bundling_suggestion'] = f"Bundle with top-seller in {item['department']} (avg sales: {int(item['top_seller_avg'])} units/mo)"
            else:
                item['bundling_suggestion'] = "Bundle with high-demand items like Coca Cola"
            
            # Loyalty note
            item['loyalty_tip'] = "Offer extra loyalty points for purchase"
        
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/dead_stock', methods=['GET'])
@jwt_required()
def get_dead_stock():
    try:
        months_back = int(request.args.get('months_back', 3))  # Default: last 3 months
        low_sales_threshold = int(request.args.get('low_sales_threshold', 50))  # Customizable
        high_stock_threshold = int(request.args.get('high_stock_threshold', 20))
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Dynamic last N months: e.g., for Oct 2025, months 8-10 in 2025
        cursor.execute("""
            SELECT 
                i.item_name, 
                inv.product_name, 
                inv.stock_quantity, 
                COALESCE(SUM(sh.quantity_sold), 0) as recent_sales,
                inv.expire_date
            FROM inventory inv
            JOIN items i ON inv.product_code = i.item_code
            LEFT JOIN sales_history sh ON i.item_id = sh.item_id 
                AND sh.year = YEAR(CURDATE()) 
                AND sh.month >= MONTH(CURDATE()) - %s + 1
                AND sh.month <= MONTH(CURDATE())
            WHERE inv.stock_quantity > %s
            GROUP BY i.item_id, inv.id
            HAVING recent_sales < %s
            ORDER BY recent_sales ASC, inv.stock_quantity DESC
        """, (months_back, high_stock_threshold, low_sales_threshold))
        dead_items = cursor.fetchall()
        conn.close()
        
        # Add recommendations (simple rules)
        for item in dead_items:
            if item['stock_quantity'] > 100:
                item['recommendation'] = 'Recommend 30% discount to clear high stock'
            elif item['recent_sales'] == 0:
                item['recommendation'] = 'Obsolete: Consider removal or bundling with popular items like Coca Cola'
            else:
                item['recommendation'] = f'Recommend {int((low_sales_threshold - item["recent_sales"]) * 0.5)}% discount or bundle promotion'
        
        return jsonify(dead_items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)