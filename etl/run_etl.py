"""
Dublin Mobility ETL Script
Runs every 5 minutes via GitHub Actions
Fetches GTFS-R data from NTA and loads into Neon PostgreSQL
"""

import os
import json
import requests
import psycopg2
from datetime import datetime, timedelta
from google.transit import gtfs_realtime_pb2

# --- Configuration ---
NTA_API_KEY = os.environ.get("NTA_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

VEHICLE_POSITIONS_URL = "https://api.nationaltransport.ie/gtfsr/v2/Vehicles"
TRIP_UPDATES_URL = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates"

def get_db_connection():
    """Create database connection"""
    return psycopg2.connect(DATABASE_URL)

def create_tables_if_not_exist(conn):
    """Create bronze tables if they don't exist"""
    with conn.cursor() as cur:
        # Bronze vehicle positions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bronze_vehicle_positions (
                vehicle_id VARCHAR(100),
                trip_id VARCHAR(100),
                route_id VARCHAR(100),
                raw_data JSONB,
                ingestion_timestamp TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (vehicle_id, trip_id)
            )
        """)
        
        # Bronze trip updates
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bronze_trip_updates (
                trip_id VARCHAR(100),
                route_id VARCHAR(100),
                raw_data JSONB,
                ingestion_timestamp TIMESTAMP DEFAULT NOW(),
                PRIMARY KEY (trip_id)
            )
        """)
        
        conn.commit()
    print("✅ Tables verified/created")

def fetch_vehicle_positions():
    """Fetch vehicle positions from NTA GTFS-R feed"""
    headers = {"x-api-key": NTA_API_KEY}
    response = requests.get(VEHICLE_POSITIONS_URL, headers=headers)
    response.raise_for_status()
    
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    
    vehicles = []
    for entity in feed.entity:
        if entity.HasField("vehicle"):
            v = entity.vehicle
            vehicles.append({
                "vehicle_id": v.vehicle.id,
                "trip_id": v.trip.trip_id,
                "route_id": v.trip.route_id,
                "raw_data": {
                    "lat": v.position.latitude,
                    "lon": v.position.longitude,
                    "timestamp": v.timestamp,
                    "route_id": v.trip.route_id
                }
            })
    
    print(f"📍 Fetched {len(vehicles)} vehicle positions")
    return vehicles

def fetch_trip_updates():
    """Fetch trip updates from NTA GTFS-R feed"""
    headers = {"x-api-key": NTA_API_KEY}
    response = requests.get(TRIP_UPDATES_URL, headers=headers)
    response.raise_for_status()
    
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    
    updates = []
    for entity in feed.entity:
        if entity.HasField("trip_update"):
            tu = entity.trip_update
            # Get delay from first stop time update
            delay = None
            stop_id = None
            if tu.stop_time_update:
                stu = tu.stop_time_update[0]
                if stu.HasField("arrival"):
                    delay = stu.arrival.delay
                elif stu.HasField("departure"):
                    delay = stu.departure.delay
                stop_id = stu.stop_id
            
            if delay is not None:
                updates.append({
                    "trip_id": tu.trip.trip_id,
                    "route_id": tu.trip.route_id,
                    "raw_data": {
                        "delay": delay,
                        "stop_id": stop_id
                    }
                })
    
    print(f"⏱️ Fetched {len(updates)} trip updates")
    return updates

def load_vehicle_positions(conn, vehicles):
    """Upsert vehicle positions into bronze table"""
    with conn.cursor() as cur:
        for v in vehicles:
            cur.execute("""
                INSERT INTO bronze_vehicle_positions (vehicle_id, trip_id, route_id, raw_data, ingestion_timestamp)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (vehicle_id, trip_id) 
                DO UPDATE SET raw_data = EXCLUDED.raw_data, ingestion_timestamp = NOW()
            """, (v["vehicle_id"], v["trip_id"], v["route_id"], json.dumps(v["raw_data"])))
        conn.commit()
    print(f"✅ Loaded {len(vehicles)} vehicle positions")

def load_trip_updates(conn, updates):
    """Upsert trip updates into bronze table"""
    with conn.cursor() as cur:
        for u in updates:
            cur.execute("""
                INSERT INTO bronze_trip_updates (trip_id, route_id, raw_data, ingestion_timestamp)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (trip_id) 
                DO UPDATE SET raw_data = EXCLUDED.raw_data, ingestion_timestamp = NOW()
            """, (u["trip_id"], u["route_id"], json.dumps(u["raw_data"])))
        conn.commit()
    print(f"✅ Loaded {len(updates)} trip updates")

def run_dbt_models(conn):
    """Run dbt transformations as raw SQL (simplified for GitHub Actions)"""
    
    # Silver Vehicle Positions
    silver_vehicle_positions = """
    DROP TABLE IF EXISTS silver_vehicle_positions;
    CREATE TABLE silver_vehicle_positions AS
    SELECT
        vehicle_id,
        trip_id,
        (raw_data::jsonb ->> 'lat')::float as latitude,
        (raw_data::jsonb ->> 'lon')::float as longitude,
        raw_data::jsonb ->> 'route_id' as route_id,
        TO_TIMESTAMP((raw_data::jsonb ->> 'timestamp')::bigint) as gps_timestamp,
        ingestion_timestamp as loaded_at
    FROM bronze_vehicle_positions
    WHERE raw_data::jsonb ->> 'lat' IS NOT NULL
    """
    
    # Silver Trip Updates
    silver_trip_updates = """
    DROP TABLE IF EXISTS silver_trip_updates;
    CREATE TABLE silver_trip_updates AS
    SELECT
        trip_id,
        route_id,
        (raw_data::jsonb ->> 'delay')::int as delay_seconds,
        raw_data::jsonb ->> 'stop_id' as stop_id,
        ingestion_timestamp as loaded_at
    FROM bronze_trip_updates
    WHERE raw_data::jsonb ->> 'delay' IS NOT NULL
    """
    
    with conn.cursor() as cur:
        print("🔄 Running silver_vehicle_positions...")
        cur.execute(silver_vehicle_positions)
        
        print("🔄 Running silver_trip_updates...")
        cur.execute(silver_trip_updates)
        
        conn.commit()
    
    print("✅ dbt models completed")

def prune_old_data(conn, hours=24):
    """Delete data older than specified hours to stay within 512MB limit"""
    with conn.cursor() as cur:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        cur.execute("DELETE FROM bronze_vehicle_positions WHERE ingestion_timestamp < %s", (cutoff,))
        deleted_vehicles = cur.rowcount
        
        cur.execute("DELETE FROM bronze_trip_updates WHERE ingestion_timestamp < %s", (cutoff,))
        deleted_updates = cur.rowcount
        
        conn.commit()
    
    print(f"🗑️ Pruned {deleted_vehicles} old vehicle records, {deleted_updates} old trip updates")

def main():
    print(f"\n{'='*50}")
    print(f"🚌 Dublin Mobility ETL - {datetime.utcnow().isoformat()}")
    print(f"{'='*50}\n")
    
    if not NTA_API_KEY:
        raise ValueError("NTA_API_KEY environment variable not set")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")
    
    conn = get_db_connection()
    
    try:
        # Create tables if needed
        create_tables_if_not_exist(conn)
        
        # Fetch data
        vehicles = fetch_vehicle_positions()
        updates = fetch_trip_updates()
        
        # Load data
        load_vehicle_positions(conn, vehicles)
        load_trip_updates(conn, updates)
        
        # Transform
        run_dbt_models(conn)
        
        # Prune old data (keep last 24 hours)
        prune_old_data(conn, hours=24)
        
        print(f"\n✅ ETL completed successfully!\n")
        
    finally:
        conn.close()

if __name__ == "__main__":
    main()