# app.py

from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
import pandas as pd
import pickle
from datetime import datetime
import numpy as np

app = Flask(__name__)
CORS(app)  # Enable CORS for React frontend

# Load the trained Random Forest model
with open('model.pickle', 'rb') as file:  # Use the correct file name
    model = pickle.load(file)

# MySQL database configuration (using XAMPP default settings)
db_config = {
    'user': 'root',
    'password': '',  # Default XAMPP MySQL has no password unless changed
    'host': 'localhost',
    'database': 'stockly'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

@app.route('/add_inventory', methods=['POST'])
def add_inventory():
    data = request.json
    # Validate required fields
    required_fields = ['record_date', 'product_id', 'product_name', 'supplier', 'stock_quantity', 'reorder_level', 'reorder_quantity', 'units_sold', 'last_sold_date', 'last_restock_date', 'next_restock_date']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing required fields'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    query = """
    INSERT INTO inventory (record_date, product_id, product_name, supplier, stock_quantity, reorder_level, reorder_quantity, units_sold, last_sold_date, last_restock_date, next_restock_date)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        data['record_date'], data['product_id'], data['product_name'], data['supplier'],
        data['stock_quantity'], data['reorder_level'], data['reorder_quantity'], data['units_sold'],
        data.get('last_sold_date') or None, data['last_restock_date'], data['next_restock_date']
    )
    cursor.execute(query, values)
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'message': 'Inventory added successfully'}), 201

@app.route('/predict_reorder', methods=['POST'])
def predict_reorder():
    data = request.json
    product_name = data['product_name']
    supplier = data['supplier']

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Fetch the latest row for the product_name and supplier (based on max record_date)
    cursor.execute("""
        SELECT * FROM inventory 
        WHERE product_name = %s AND supplier = %s 
        ORDER BY record_date DESC LIMIT 1
    """, (product_name, supplier))
    latest_row = cursor.fetchone()
    if not latest_row:
        return jsonify({'error': 'No data found for the given product and supplier'}), 404

    # Compute days features based on current date
    current_date = datetime.now().date()
    days_since_date = (current_date - latest_row['record_date']).days
    days_since_last_sold = (current_date - latest_row['last_sold_date']).days if latest_row['last_sold_date'] else 0
    days_since_last_restock = (current_date - latest_row['last_restock_date']).days
    days_until_next_restock = (latest_row['next_restock_date'] - current_date).days

    # Numerical features
    numerical = {
        'StockQuantity': latest_row['stock_quantity'],
        'ReorderLevel': latest_row['reorder_level'],
        'UnitsSold': latest_row['units_sold'],
        'DaysSinceDate': days_since_date,
        'DaysSinceLastSoldDate': days_since_last_sold,
        'DaysSinceLastRestockDate': days_since_last_restock,
        'DaysUntilNextRestockDate': days_until_next_restock
    }

    # Create input row DF with proper prefixes
    input_df = pd.DataFrame({
        'ProductName': [product_name],
        'Supplier': [supplier]
    })
    input_one_hot = pd.get_dummies(input_df, columns=['ProductName', 'Supplier'])

    # Define the exact feature names the model was trained on (from Colab output)
    expected_features = [
        'StockQuantity', 'ReorderLevel', 'UnitsSold', 'DaysSinceDate',
        'DaysSinceLastSoldDate', 'DaysSinceLastRestockDate', 'DaysUntilNextRestockDate',
        'ProductName_Asamodagam', 'ProductName_Astra packet', 'ProductName_Baby Soap',
        'ProductName_Balm', 'ProductName_Beedi', 'ProductName_Big Union', 'ProductName_Blue Pen',
        'ProductName_Book(Single 80)', 'ProductName_Bread', 'ProductName_Chocolate',
        'ProductName_Cream Bun', 'ProductName_Cream Cracker', 'ProductName_Data 99',
        'ProductName_Dhal', 'ProductName_Dry Fish', 'ProductName_Flour', 'ProductName_Glue',
        'ProductName_Incense sticks', 'ProductName_Laundry Detergent', 'ProductName_Matchbox',
        'ProductName_Milk Powder', 'ProductName_Milo', 'ProductName_Murukku Packet',
        'ProductName_Noodles', 'ProductName_Pahanthira', 'ProductName_Pencil', 'ProductName_Razor',
        'ProductName_Reload 100', 'ProductName_Rice', 'ProductName_Salt', 'ProductName_Samon',
        'ProductName_Seasoning Cube', 'ProductName_Shampoo', 'ProductName_Soap',
        'ProductName_Soya Meat', 'ProductName_Sprite', 'ProductName_Sugar', 'ProductName_Tea Powder',
        'ProductName_Toffees', 'ProductName_Tooth Brush', 'ProductName_Toothpaste',
        'ProductName_Umbalakada Powder', 'ProductName_Yogurt', 'ProductName_eggs',
        'ProductName_ice packet', 'Supplier_Ambewela', 'Supplier_Amritha', 'Supplier_Anil',
        'Supplier_Araliya', 'Supplier_Asiri', 'Supplier_Astra', 'Supplier_Atlas',
        'Supplier_Bathi Pooja', 'Supplier_CIC', 'Supplier_Center Fruit', 'Supplier_Chello',
        'Supplier_Clogard', 'Supplier_DB', 'Supplier_Dandex', 'Supplier_Delta', 'Supplier_Denta',
        'Supplier_Dialog', 'Supplier_Diva', 'Supplier_Finagle', 'Supplier_Gajamuthu',
        'Supplier_Hacks', 'Supplier_Harischandra', 'Supplier_Highland', 'Supplier_Hutch',
        'Supplier_Iodex', 'Supplier_JLK', 'Supplier_Jack Mackerel', 'Supplier_Jayasinghe',
        'Supplier_Jeewaka', 'Supplier_Kamalesan', 'Supplier_Kanchana', 'Supplier_Kandos',
        'Supplier_Kasun', 'Supplier_Knorr', 'Supplier_Kumara', 'Supplier_Lakmal',
        'Supplier_Lakspray', 'Supplier_Lanka Salt', 'Supplier_Lanka Soy', 'Supplier_Laogee',
        'Supplier_Lifeboy', 'Supplier_Lux', 'Supplier_Maggi', 'Supplier_Maliban',
        'Supplier_Mango', 'Supplier_Meegoda', 'Supplier_Mobitel', 'Supplier_Munchee',
        'Supplier_My Lady', 'Supplier_NBC', 'Supplier_NSD Agro', 'Supplier_Nataraj',
        'Supplier_Nestle', 'Supplier_Newdale', 'Supplier_Nimal', 'Supplier_Nipuna',
        'Supplier_Ocean Star', 'Supplier_Pears', 'Supplier_Pertamina Group',
        'Supplier_Prima Kottumee', 'Supplier_Promate', 'Supplier_Raigam',
        'Supplier_Raigam Devani Batha', 'Supplier_Rajesh', 'Supplier_Ran Kahata',
        'Supplier_Ran Ovens', 'Supplier_Ranjan', 'Supplier_Rashmi', 'Supplier_Ratna',
        'Supplier_Ratthi', 'Supplier_Ravi', 'Supplier_Rich life', 'Supplier_Richy',
        'Supplier_Rin', 'Supplier_Ritzbury', 'Supplier_Roshan', 'Supplier_Ruhunu', 'Supplier_SP',
        'Supplier_Safee', 'Supplier_Sahan', 'Supplier_Samantha', 'Supplier_Samarasinghe',
        'Supplier_Sapumal', 'Supplier_Sathosa', 'Supplier_Siddhalepa', 'Supplier_Signal',
        'Supplier_Sithumina', 'Supplier_Smack', 'Supplier_Soorya', 'Supplier_Sujeewa',
        'Supplier_Suliko', 'Supplier_Sunimal', 'Supplier_Sunlight', 'Supplier_Sunsilk',
        'Supplier_Swadeshi', 'Supplier_Ten', 'Supplier_Unilever', 'Supplier_Uswatte',
        'Supplier_Velvete', 'Supplier_Vendol', 'Supplier_Watawala', 'Supplier_Yatawara'
    ]

    # Align input_one_hot to include all expected features, filling missing with 0
    input_one_hot = input_one_hot.reindex(columns=[col for col in expected_features if col.startswith('ProductName_') or col.startswith('Supplier_')], fill_value=0)

    # Combine numerical and one-hot
    numerical_df = pd.DataFrame([numerical])
    X = pd.concat([numerical_df, input_one_hot], axis=1)

    # Reindex X to match all expected features, filling missing with 0
    X = X.reindex(columns=expected_features, fill_value=0)

    # Debug: Print X columns to verify
    print("X columns:", X.columns.tolist())

    # Predict
    prediction = model.predict(X)[0]

    return jsonify({'predicted_reorder_quantity': int(prediction)})

if __name__ == '__main__':
    app.run(debug=True, port=5000)