# app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import joblib
import pandas as pd
import numpy as np

app = Flask(__name__)
CORS(app)

# Load dataset (used for feature extraction)
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

        # Predict
        pred_qty = float(xgb_model.predict(sample_df)[0])

        return jsonify({'predicted_reorder_quantity': pred_qty})

    except Exception as e:
        return jsonify({'error': str(e)}), 400

if __name__ == "__main__":
    app.run(debug=True)
