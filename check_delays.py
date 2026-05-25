from sqlalchemy import create_engine, text
import pandas as pd

DB_CONN = "postgresql+psycopg2://airflow:airflow@localhost:5432/mobility_db"
engine = create_engine(DB_CONN)

# Query 1: Check delay distribution
query1 = """
SELECT 
    COUNT(*) as total_records,
    COUNT(CASE WHEN (raw_data ->> 'delay')::int = 0 THEN 1 END) as zero_delay,
    COUNT(CASE WHEN (raw_data ->> 'delay')::int > 0 THEN 1 END) as positive_delay,
    COUNT(CASE WHEN (raw_data ->> 'delay')::int < 0 THEN 1 END) as negative_delay,
    COUNT(CASE WHEN raw_data ->> 'delay' IS NULL THEN 1 END) as null_delay
FROM bronze_trip_updates;
"""

# Query 2: Check vehicles without delay records
query2 = """
SELECT 
    COUNT(DISTINCT vp.trip_id) as vehicles_with_gps,
    COUNT(DISTINCT tu.trip_id) as vehicles_with_delay
FROM bronze_vehicle_positions vp
LEFT JOIN bronze_trip_updates tu ON vp.trip_id = tu.trip_id;
"""

with engine.connect() as conn:
    print("=== DELAY DISTRIBUTION ===")
    df1 = pd.read_sql(text(query1), conn)
    print(df1.to_string(index=False))
    
    print("\n=== VEHICLES GPS vs DELAY ===")
    df2 = pd.read_sql(text(query2), conn)
    print(df2.to_string(index=False))
    print(f"\nVehicles WITHOUT delay record: {df2['vehicles_with_gps'].iloc[0] - df2['vehicles_with_delay'].iloc[0]}")