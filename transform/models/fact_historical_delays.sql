{{ config(
    materialized='incremental',
    unique_key='delay_record_id',
    on_schema_change='append_new_columns'
) }}

WITH delay_snapshots AS (
    SELECT
        -- Create unique ID for each record (trip_id + timestamp combo)
        {{ dbt_utils.generate_surrogate_key(['trip_id', 'loaded_at']) }} as delay_record_id,
        
        trip_id,
        route_id,
        SPLIT_PART(route_id, '_', 1) as route_code,
        delay_seconds,
        ROUND(delay_seconds / 60.0, 2) as delay_minutes,
        
        -- Categorize delay
        CASE
            WHEN delay_seconds < 0 THEN 'early'
            WHEN delay_seconds / 60.0 <= 2 THEN 'on_time'
            WHEN delay_seconds / 60.0 <= 5 THEN 'minor'
            WHEN delay_seconds / 60.0 <= 10 THEN 'moderate'
            WHEN delay_seconds / 60.0 <= 20 THEN 'severe'
            ELSE 'critical'
        END as delay_category,
        
        stop_id,
        loaded_at as recorded_at,
        
        -- Time dimensions for analysis
        DATE(loaded_at) as record_date,
        EXTRACT(HOUR FROM loaded_at)::int as record_hour,
        EXTRACT(DOW FROM loaded_at)::int as day_of_week,  -- 0=Sunday, 1=Monday, etc.
        TRIM(TO_CHAR(loaded_at, 'Day')) as day_name,
        CASE 
            WHEN EXTRACT(HOUR FROM loaded_at) BETWEEN 7 AND 9 THEN 'morning_rush'
            WHEN EXTRACT(HOUR FROM loaded_at) BETWEEN 12 AND 14 THEN 'lunch'
            WHEN EXTRACT(HOUR FROM loaded_at) BETWEEN 16 AND 19 THEN 'evening_rush'
            WHEN EXTRACT(HOUR FROM loaded_at) >= 22 OR EXTRACT(HOUR FROM loaded_at) <= 5 THEN 'night'
            ELSE 'off_peak'
        END as time_period
        
    FROM {{ ref('silver_trip_updates') }}
    
    {% if is_incremental() %}
        -- Only process new records since last run
        WHERE loaded_at > (SELECT COALESCE(MAX(recorded_at), '1900-01-01'::timestamp) FROM {{ this }})
    {% endif %}
)

SELECT * FROM delay_snapshots