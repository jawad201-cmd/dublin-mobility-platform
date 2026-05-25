{{ config(materialized='table') }}

-- Dimension table for routes
-- Provides lookup information for each route pattern

WITH route_stats AS (
    SELECT
        SPLIT_PART(route_id, '_', 1) as route_code,
        route_id as route_pattern,
        COUNT(*) as total_observations,
        COUNT(DISTINCT trip_id) as unique_trips,
        MIN(loaded_at) as first_seen,
        MAX(loaded_at) as last_seen,
        
        -- Delay statistics for this route pattern
        ROUND(AVG(delay_seconds / 60.0), 2) as avg_delay_minutes,
        ROUND(MAX(delay_seconds / 60.0), 2) as max_delay_minutes,
        ROUND(MIN(delay_seconds / 60.0), 2) as min_delay_minutes,
        
        -- Performance metrics
        ROUND(
            100.0 * COUNT(CASE WHEN delay_seconds / 60.0 <= 2 THEN 1 END) / NULLIF(COUNT(*), 0),
            2
        ) as on_time_percentage
        
    FROM {{ ref('silver_trip_updates') }}
    WHERE delay_seconds IS NOT NULL
    GROUP BY route_code, route_pattern
)

SELECT
    route_code,
    route_pattern,
    total_observations,
    unique_trips,
    first_seen,
    last_seen,
    avg_delay_minutes,
    max_delay_minutes,
    min_delay_minutes,
    on_time_percentage,
    
    -- Calculate days active
    DATE_PART('day', last_seen - first_seen) + 1 as days_active
    
FROM route_stats
ORDER BY route_code, route_pattern