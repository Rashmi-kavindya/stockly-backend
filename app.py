# app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import pandas as pd
import numpy as np
import mysql.connector
from mysql.connector import Error
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# DB Connection
def get_db_connection():
    return mysql.connector.connect(
        host='localhost', user='root', password='',
        database='stockly_db'
    )

# Load dataset (used for feature extraction) - Keep for predict compat, but use DB for new features
df = pd.read_csv('sri_dataset.csv')  # your dataset path
df.fillna(0, inplace=True)

# Load trained model and feature columns
xgb_model = joblib.load('stockly_xgb_model.pkl')
feature_columns = joblib.load('stockly_feature_columns.pkl')

@app.route('/')
def home():
    return "Stockly API is running"

@app.route('/predict_reorder', methods=['POST'])
def predict_reorder():
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

        return jsonify({'predicted_reorder_quantity': pred_qty})

    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/items', methods=['GET'])
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
def add_inventory():
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
        return jsonify({'message': 'Inventory updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/inventory', methods=['GET'])
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

@app.route('/sales/<int:item_id>', methods=['GET'])
def get_sales(item_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT month, year, quantity_sold FROM sales_history 
            WHERE item_id = %s ORDER BY year DESC, month DESC LIMIT 12
        """, (item_id,))
        data = cursor.fetchall()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/near_expiry', methods=['GET'])
def get_near_expiry():
    days_threshold = int(request.args.get('days', 30))
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT product_name, stock_quantity, expire_date,
                   DATEDIFF(expire_date, CURDATE()) as days_left
            FROM inventory 
            WHERE expire_date >= CURDATE() AND DATEDIFF(expire_date, CURDATE()) <= %s
            ORDER BY expire_date ASC
        """, (days_threshold,))
        items = cursor.fetchall()
        # Recommend discount: 10% per week left (simple rule)
        for item in items:
            weeks_left = item['days_left'] / 7
            item['recommended_discount'] = max(10, 100 - int(weeks_left * 10))  # e.g., 50% if 5 weeks left
        conn.close()
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# NEW: Dead Stock API (add this route)
@app.route('/dead_stock', methods=['GET'])
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