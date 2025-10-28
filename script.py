# import pandas as pd
# import mysql.connector

# # ---------- 1. Read your dataset ----------
# # Replace with your actual dataset file name
# df = pd.read_csv("sri_dataset.csv")  

# # ---------- 2. Extract unique items ----------
# # Keep only relevant columns and drop duplicates
# unique_items = df[['CODE', 'ITEM NAME', 'DEPARTMENT', 'TYPE']].drop_duplicates(subset=['ITEM NAME', 'DEPARTMENT', 'TYPE']).reset_index(drop=True)

# # Create a sequential item_code for clean referencing
# unique_items.insert(0, 'item_code', range(1, len(unique_items) + 1))

# print(f"✅ Found {len(unique_items)} unique items")
# print(unique_items.head())

# # ---------- 3. Connect to MySQL ----------
# connection = mysql.connector.connect(
#     host='localhost',
#     user='root',
#     password='',      
#     database='stockly_db' 
# )

# cursor = connection.cursor()

# # ---------- 4. Create table if not exists ----------
# create_table_query = """
# CREATE TABLE IF NOT EXISTS items (
#     item_code INT PRIMARY KEY,
#     item_name VARCHAR(255) NOT NULL,
#     department VARCHAR(100) NOT NULL,
#     type VARCHAR(100) NOT NULL
# )
# """
# cursor.execute(create_table_query)
# print("✅ Table 'items' checked/created successfully")

# # ---------- 5. Insert unique items ----------
# insert_query = """
# INSERT INTO items (item_code, item_name, department, type)
# VALUES (%s, %s, %s, %s)
# """

# for _, row in unique_items.iterrows():
#     cursor.execute(insert_query, (int(row['item_code']), row['ITEM NAME'], row['DEPARTMENT'], row['TYPE']))

# connection.commit()
# print(f"✅ Inserted {len(unique_items)} unique items successfully!")

# # ---------- 6. Close connection ----------
# cursor.close()
# connection.close()
# print("🔒 Database connection closed.")


import pandas as pd
import mysql.connector

# ======== Step 1: Load dataset ==========
file_path = "dataset.csv"  # <-- change if needed
df = pd.read_csv(file_path)

print("\n=== Dataset Loaded ===")
print(f"Shape: {df.shape}")
print("\nColumns:", list(df.columns))
print("\nSample Data:")
print(df.head())

# ======== Step 2: Summary check ==========
unique_items = df["ITEM NAME"].nunique()
print(f"\nTotal Records: {len(df)}")
print(f"Unique Items: {unique_items}")

# ======== Step 3: Confirm before inserting ==========
confirm = input("\nDo you want to insert this data into MySQL? (y/n): ").strip().lower()
if confirm != 'y':
    print("\n❌ Insert cancelled. No changes made.")
    exit()

# ======== Step 4: Connect to MySQL ==========
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",  # <-- change this
    database="stockly_db"
)
cursor = db.cursor()

# ======== Step 5: Prepare item table insertion ==========
print("\nInserting unique items into `items` table...")
unique_items_df = df[["ITEM NAME", "TYPE", "DEPARTMENT"]].drop_duplicates().reset_index(drop=True)

for idx, row in unique_items_df.iterrows():
    item_code = str(100 + idx)
    cursor.execute("""
        INSERT INTO items (item_code, item_name, department, type)
        VALUES (%s, %s, %s, %s)
    """, (item_code, row["ITEM NAME"], row["DEPARTMENT"], row["TYPE"]))

db.commit()
print(f"✅ Inserted {len(unique_items_df)} items into `items` table.")

# ======== Step 6: Map item IDs ==========
cursor.execute("SELECT item_id, item_name FROM items")
item_map = {name: item_id for item_id, name in cursor.fetchall()}

# ======== Step 7: Insert into sales_history ==========
print("\nInserting records into `sales_history` table...")
for _, row in df.iterrows():
    item_id = item_map.get(row["ITEM NAME"])
    cursor.execute("""
        INSERT INTO sales_history (item_id, month, year, quantity_sold, `rank`, code, record_date)
        VALUES (%s, %s, %s, %s, %s, %s, CURDATE())
    """, (item_id, row["MONTH"], 2024, row["QUANTITY"], row["RANK"], row["CODE"]))

db.commit()
print(f"✅ Inserted {len(df)} sales records into `sales_history` table.")