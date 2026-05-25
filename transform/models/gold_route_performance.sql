{{ config(materialized='table') }}

SELECT
    route_id,
    -- KPI 1: How many buses are running on this route?
    COUNT(DISTINCT trip_id) as active_buses,
    
    -- KPI 2: What is the average delay? (Converted to minutes)
    ROUND(AVG(delay_seconds) / 60, 2) as avg_delay_minutes,
    
    -- KPI 3: The worst delay currently recorded
    MAX(delay_seconds) / 60 as max_delay_minutes

FROM {{ ref('silver_trip_updates') }}
GROUP BY route_id
ORDER BY avg_delay_minutes DESC