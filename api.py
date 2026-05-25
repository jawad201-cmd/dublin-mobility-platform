import os
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
import pandas as pd
import math
from typing import Optional

app = FastAPI(
    title="Dublin Mobility Intelligence API",
    description="Real-time transit performance monitoring for Dublin",
    version="1.1.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection - use environment variable for cloud, fallback for local
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg2://airflow:airflow@localhost:5432/mobility_db")

# Fix for Render/Neon - they use 'postgres://' but SQLAlchemy needs 'postgresql://'
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

# Connect to Docker DB
DB_CONN = "postgresql+psycopg2://airflow:airflow@localhost:5432/mobility_db"
engine = create_engine(DB_CONN)


def clean_value(val):
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return val

def clean_records(df):
    records = df.to_dict(orient="records")
    return [{k: clean_value(v) for k, v in row.items()} for row in records]


@app.get("/")
def home():
    return {
        "message": "Dublin Mobility Intelligence API",
        "version": "1.1.0",
        "endpoints": ["/vehicles", "/delays", "/delays/summary", "/routes", "/health", "/analytics/worst-routes"]
    }


@app.get("/vehicles")
def get_vehicles():
    """Returns the latest GPS position for every bus."""
    query = """
    SELECT DISTINCT ON (vehicle_id) 
        vehicle_id, trip_id, latitude, longitude, route_id, gps_timestamp
    FROM silver_vehicle_positions
    ORDER BY vehicle_id, gps_timestamp DESC;
    """
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    return clean_records(df)


@app.get("/delays")
def get_delays(
    category: Optional[str] = Query(None, description="Filter by category: early, on_time, minor, moderate, severe, critical"),
    route: Optional[str] = Query(None, description="Filter by route ID"),
    limit: int = Query(5000, description="Maximum results", le=10000)
):
    """
    Returns trips with their LATEST delay value and TREND indicator.
    Trend compares current delay with delay from 30 minutes ago.
    """
    
    # Build route filter
    route_filter = f"AND route_id LIKE '{route}%'" if route else ""
    
    # Build category filter
    category_filter = ""
    if category:
        category_conditions = {
            'early': "delay_category = 'early'",
            'on_time': "delay_category = 'on_time'",
            'minor': "delay_category = 'minor'",
            'moderate': "delay_category = 'moderate'",
            'severe': "delay_category = 'severe'",
            'critical': "delay_category = 'critical'"
        }
        if category.lower() in category_conditions:
            category_filter = f"WHERE {category_conditions[category.lower()]}"
    
    query = f"""
    WITH latest_delay_per_trip AS (
        -- Step 1: Get the SINGLE most recent delay for each trip
        SELECT DISTINCT ON (trip_id)
            trip_id,
            route_id,
            delay_seconds,
            loaded_at
        FROM silver_trip_updates
        WHERE delay_seconds IS NOT NULL {route_filter}
        ORDER BY trip_id, loaded_at DESC
    ),
    previous_delay_per_trip AS (
        -- Step 2: Get the delay from ~30 minutes ago for trend comparison
        SELECT DISTINCT ON (trip_id)
            trip_id,
            delay_seconds as prev_delay_seconds,
            loaded_at as prev_loaded_at
        FROM silver_trip_updates
        WHERE delay_seconds IS NOT NULL 
          AND loaded_at < (NOW() - INTERVAL '25 minutes')
          {route_filter}
        ORDER BY trip_id, loaded_at DESC
    ),
    categorized_delays AS (
        -- Step 3: Calculate delay minutes, category, and trend
        SELECT
            ld.trip_id,
            ld.route_id,
            ld.delay_seconds,
            ROUND((ld.delay_seconds / 60.0)::numeric, 2) as avg_delay_minutes,
            CASE
                WHEN ld.delay_seconds < 0 THEN 'early'
                WHEN ld.delay_seconds / 60.0 <= 2 THEN 'on_time'
                WHEN ld.delay_seconds / 60.0 <= 5 THEN 'minor'
                WHEN ld.delay_seconds / 60.0 <= 10 THEN 'moderate'
                WHEN ld.delay_seconds / 60.0 <= 20 THEN 'severe'
                ELSE 'critical'
            END as delay_category,
            ld.loaded_at,
            -- Previous delay info
            pd.prev_delay_seconds,
            ROUND((pd.prev_delay_seconds / 60.0)::numeric, 2) as prev_delay_minutes,
            -- Calculate trend
            CASE
                WHEN pd.prev_delay_seconds IS NULL THEN 'new'
                WHEN ld.delay_seconds > pd.prev_delay_seconds + 60 THEN 'worsening'  -- More than 1 min increase
                WHEN ld.delay_seconds < pd.prev_delay_seconds - 60 THEN 'improving'  -- More than 1 min decrease
                ELSE 'stable'
            END as trend,
            -- Calculate change in minutes
            CASE
                WHEN pd.prev_delay_seconds IS NULL THEN NULL
                ELSE ROUND(((ld.delay_seconds - pd.prev_delay_seconds) / 60.0)::numeric, 1)
            END as trend_change_minutes
        FROM latest_delay_per_trip ld
        LEFT JOIN previous_delay_per_trip pd ON ld.trip_id = pd.trip_id
    ),
    filtered_delays AS (
        -- Step 4: Apply category filter if specified
        SELECT * FROM categorized_delays
        {category_filter}
    ),
    latest_positions AS (
        -- Step 5: Get latest GPS position for each trip
        SELECT DISTINCT ON (trip_id)
            trip_id,
            latitude,
            longitude,
            gps_timestamp
        FROM silver_vehicle_positions
        ORDER BY trip_id, gps_timestamp DESC
    )
    -- Step 6: Join and return results
    SELECT 
        fd.trip_id as route_id,
        fd.avg_delay_minutes,
        fd.delay_category,
        fd.trend,
        fd.trend_change_minutes,
        fd.prev_delay_minutes,
        lp.latitude as last_lat,
        lp.longitude as last_lon,
        lp.gps_timestamp as last_seen
    FROM filtered_delays fd
    LEFT JOIN latest_positions lp ON fd.trip_id = lp.trip_id
    ORDER BY fd.loaded_at DESC
    LIMIT {limit};
    """

    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    
    return clean_records(df)


@app.get("/delays/summary")
def get_delays_summary():
    """
    Returns a summary count of delays by category with trend info and mappable counts.
    """
    query = """
    WITH latest_delay_per_trip AS (
        SELECT DISTINCT ON (trip_id)
            trip_id,
            delay_seconds,
            loaded_at
        FROM silver_trip_updates
        WHERE delay_seconds IS NOT NULL
        ORDER BY trip_id, loaded_at DESC
    ),
    previous_delay_per_trip AS (
        SELECT DISTINCT ON (trip_id)
            trip_id,
            delay_seconds as prev_delay_seconds
        FROM silver_trip_updates
        WHERE delay_seconds IS NOT NULL 
          AND loaded_at < (NOW() - INTERVAL '25 minutes')
        ORDER BY trip_id, loaded_at DESC
    ),
    trips_with_gps AS (
        SELECT DISTINCT trip_id
        FROM silver_vehicle_positions
    ),
    categorized_current AS (
        SELECT 
            ld.trip_id,
            CASE
                WHEN ld.delay_seconds < 0 THEN 'early'
                WHEN ld.delay_seconds / 60.0 <= 2 THEN 'on_time'
                WHEN ld.delay_seconds / 60.0 <= 5 THEN 'minor'
                WHEN ld.delay_seconds / 60.0 <= 10 THEN 'moderate'
                WHEN ld.delay_seconds / 60.0 <= 20 THEN 'severe'
                ELSE 'critical'
            END as delay_category,
            CASE WHEN gps.trip_id IS NOT NULL THEN 1 ELSE 0 END as has_gps
        FROM latest_delay_per_trip ld
        LEFT JOIN trips_with_gps gps ON ld.trip_id = gps.trip_id
    ),
    categorized_previous AS (
        SELECT 
            trip_id,
            CASE
                WHEN prev_delay_seconds < 0 THEN 'early'
                WHEN prev_delay_seconds / 60.0 <= 2 THEN 'on_time'
                WHEN prev_delay_seconds / 60.0 <= 5 THEN 'minor'
                WHEN prev_delay_seconds / 60.0 <= 10 THEN 'moderate'
                WHEN prev_delay_seconds / 60.0 <= 20 THEN 'severe'
                ELSE 'critical'
            END as delay_category
        FROM previous_delay_per_trip
    ),
    current_counts AS (
        SELECT 
            delay_category, 
            COUNT(*) as count,
            SUM(has_gps) as mappable_count
        FROM categorized_current
        GROUP BY delay_category
    ),
    previous_counts AS (
        SELECT delay_category, COUNT(*) as prev_count
        FROM categorized_previous
        GROUP BY delay_category
    )
    SELECT 
        cc.delay_category,
        cc.count,
        cc.mappable_count,
        COALESCE(pc.prev_count, 0) as prev_count,
        cc.count - COALESCE(pc.prev_count, 0) as change
    FROM current_counts cc
    LEFT JOIN previous_counts pc ON cc.delay_category = pc.delay_category
    ORDER BY 
        CASE cc.delay_category
            WHEN 'early' THEN 1
            WHEN 'on_time' THEN 2
            WHEN 'minor' THEN 3
            WHEN 'moderate' THEN 4
            WHEN 'severe' THEN 5
            WHEN 'critical' THEN 6
            ELSE 7
        END;
    """
    
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    
    return clean_records(df)


@app.get("/routes")
def get_routes():
    """Returns list of unique routes."""
    query = """
    SELECT DISTINCT 
        SPLIT_PART(route_id, '_', 1) as route_code,
        COUNT(DISTINCT trip_id) as trip_count
    FROM silver_trip_updates
    GROUP BY SPLIT_PART(route_id, '_', 1)
    ORDER BY route_code;
    """
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    return clean_records(df)


@app.get("/analytics/worst-routes")
def get_worst_routes(
    day: Optional[int] = Query(None, description="Day of week (0=Sunday, 1=Monday, etc.)"),
    period: Optional[str] = Query(None, description="Time period: morning_rush, lunch, evening_rush, night, off_peak"),
    limit: int = Query(20, description="Number of results")
):
    """Returns worst performing routes from historical data."""
    
    where_clauses = ["1=1"]
    if day is not None:
        where_clauses.append(f"day_of_week = {day}")
    if period:
        where_clauses.append(f"time_period = '{period}'")
    
    where_sql = " AND ".join(where_clauses)
    
    query = f"""
    SELECT 
        route_code,
        day_name,
        time_period,
        avg_delay,
        avg_on_time_pct,
        total_critical_delays,
        total_severe_delays,
        performance_tier,
        worst_rank
    FROM gold_worst_routes_by_period
    WHERE {where_sql}
    ORDER BY worst_rank
    LIMIT {limit};
    """
    
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
        return clean_records(df)
    except Exception as e:
        return {"error": str(e), "message": "Historical data table may not exist yet. Run dbt models first."}


@app.get("/analytics/network-health")
def get_network_health():
    """Returns overall network health summary."""
    query = """
    SELECT 
        day_name,
        time_period,
        active_routes,
        total_trips,
        network_avg_delay,
        network_on_time_pct,
        network_health_score,
        network_health_status
    FROM gold_network_summary
    ORDER BY day_of_week, 
        CASE time_period
            WHEN 'morning_rush' THEN 1
            WHEN 'off_peak' THEN 2
            WHEN 'lunch' THEN 3
            WHEN 'evening_rush' THEN 4
            WHEN 'night' THEN 5
        END;
    """
    
    try:
        with engine.connect() as conn:
            df = pd.read_sql(text(query), conn)
        return clean_records(df)
    except Exception as e:
        return {"error": str(e), "message": "Network summary table may not exist yet. Run dbt models first."}


@app.get("/health")
def health_check():
    """Health check endpoint."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.get("/debug/trip/{trip_id}")
def get_trip_debug(trip_id: str):
    """Debug endpoint to see all delay records for a specific trip."""
    query = f"""
    SELECT 
        trip_id,
        route_id,
        delay_seconds,
        ROUND((delay_seconds / 60.0)::numeric, 2) as delay_minutes,
        loaded_at
    FROM silver_trip_updates
    WHERE trip_id = '{trip_id}'
    ORDER BY loaded_at DESC
    LIMIT 20;
    """
    with engine.connect() as conn:
        df = pd.read_sql(text(query), conn)
    return clean_records(df)