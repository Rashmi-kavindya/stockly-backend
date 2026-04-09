import pandas as pd
from sqlalchemy import create_engine
import time

# Paths and config
csv_path = 'sri_dataset.csv'
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '',
    'database': 'stockly_db'
}

# Engine for batching
engine = create_engine(f"mysql+mysqlconnector://{db_config['user']}:{db_config['password']}@{db_config['host']}/{db_config['database']}")

print("Loading CSV...")
start_time = time.time()
df = pd.read_csv(csv_path, low_memory=False)
df.fillna(0, inplace=True)
print(f"Loaded {len(df)} rows in {time.time() - start_time:.2f}s.")

# Add year if missing (default 2024)
if 'year' not in df.columns:
    df['year'] = 2024

# Optimized Mapping: Fetch ALL items once into a dict wich is faster than looping queries
print("Fetching all items for mapping...")
all_items = pd.read_sql("SELECT item_id, item_name FROM items", engine)
item_mapping = dict(zip(all_items['item_name'].str.strip().str.lower(), all_items['item_id']))
print(f"Mapped {len(item_mapping)} unique items from DB.")

# Apply mapping to DF
print("Applying mapping...")
df['item_name_lower'] = df['ITEM NAME'].str.strip().str.lower()
df_mapped = df[df['item_name_lower'].isin(item_mapping.keys())].copy()
df_mapped['item_id'] = df_mapped['item_name_lower'].map(item_mapping)
df_mapped.drop('item_name_lower', axis=1, inplace=True)

# Prepare columns (adjust if CSV names differ)
df_mapped['record_date'] = pd.to_datetime('today').date()
df_mapped = df_mapped[['item_id', 'MONTH', 'year', 'QUANTITY', 'RANK', 'CODE', 'record_date']].rename(columns={
    'QUANTITY': 'quantity_sold',
    'RANK': 'rank',
    'CODE': 'code'
})

# Drop any rows with NaN item_id (unmatched)
df_mapped.dropna(subset=['item_id'], inplace=True)
print(f"Prepared {len(df_mapped)} rows for insertion (skipped {len(df) - len(df_mapped)} unmatched).")

# Batch insert with progress
print("Inserting data (batched)...")
chunk_size = 5000
total_chunks = (len(df_mapped) // chunk_size) + (1 if len(df_mapped) % chunk_size else 0)
inserted_count = 0
for i in range(0, len(df_mapped), chunk_size):
    chunk = df_mapped.iloc[i:i + chunk_size]
    try:
        chunk.to_sql('sales_history', con=engine, if_exists='append', index=False, method='multi')
        inserted_count += len(chunk)
        print(f"Inserted chunk {(i // chunk_size) + 1}/{total_chunks} ({len(chunk)} rows). Total so far: {inserted_count}")
        time.sleep(0.1)  # Prevent DB overload
    except Exception as e:
        print(f"Error in chunk {(i // chunk_size) + 1}: {e}")
        # Save failed chunk to CSV for retry
        chunk.to_csv(f'failed_chunk_{i}.csv', index=False)
        break

# Final verification
final_count = pd.read_sql('SELECT COUNT(*) as count FROM sales_history', engine)['count'].iloc[0]
print(f"Migration complete in {time.time() - start_time:.2f}s! Total rows in DB: {final_count}")

print("\nSample data from sales_history:")
sample = pd.read_sql('SELECT * FROM sales_history LIMIT 5', engine)
print(sample)
