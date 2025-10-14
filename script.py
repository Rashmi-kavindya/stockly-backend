import pandas as pd
import mysql.connector

# ---------- 1. Read your dataset ----------
# Replace with your actual dataset file name
df = pd.read_csv("sri_dataset.csv")  

# ---------- 2. Extract unique items ----------
# Keep only relevant columns and drop duplicates
unique_items = df[['CODE', 'ITEM NAME', 'DEPARTMENT', 'TYPE']].drop_duplicates(subset=['ITEM NAME', 'DEPARTMENT', 'TYPE']).reset_index(drop=True)

# Create a sequential item_code for clean referencing
unique_items.insert(0, 'item_code', range(1, len(unique_items) + 1))

print(f"✅ Found {len(unique_items)} unique items")
print(unique_items.head())

# ---------- 3. Connect to MySQL ----------
connection = mysql.connector.connect(
    host='localhost',
    user='root',
    password='',      
    database='stockly_db' 
)

cursor = connection.cursor()

# ---------- 4. Create table if not exists ----------
create_table_query = """
CREATE TABLE IF NOT EXISTS items (
    item_code INT PRIMARY KEY,
    item_name VARCHAR(255) NOT NULL,
    department VARCHAR(100) NOT NULL,
    type VARCHAR(100) NOT NULL
)
"""
cursor.execute(create_table_query)
print("✅ Table 'items' checked/created successfully")

# ---------- 5. Insert unique items ----------
insert_query = """
INSERT INTO items (item_code, item_name, department, type)
VALUES (%s, %s, %s, %s)
"""

for _, row in unique_items.iterrows():
    cursor.execute(insert_query, (int(row['item_code']), row['ITEM NAME'], row['DEPARTMENT'], row['TYPE']))

connection.commit()
print(f"✅ Inserted {len(unique_items)} unique items successfully!")

# ---------- 6. Close connection ----------
cursor.close()
connection.close()
print("🔒 Database connection closed.")
