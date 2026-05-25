{{ config(materialized='table') }}

-- Overall network health summary by day and time period
-- Answers: "How is Dublin's bus network performing overall?"

WITH period_summary AS (
    SELECT
        day_of_week,
        day_name,
        time_period,
        
        -- Network-wide metrics
        COUNT(DISTINCT route_code) as active_routes,
        SUM(total_observations) as total_observations,
        SUM(unique_trips) as total_trips,
        
        -- Average performance across all routes
        ROUND(AVG(avg_delay_minutes)::numeric, 2) as network_avg_delay,
        ROUND(AVG(on_time_percentage)::numeric, 2) as network_on_time_pct,
        
        -- Problem counts
        SUM(critical_count) as network_critical_count,
        SUM(severe_count) as network_severe_count,
        
        -- Worst performing route in this period
        MAX(max_delay_minutes) as worst_delay_in_network
        
    FROM {{ ref('gold_route_performance_hourly') }}
    GROUP BY day_of_week, day_name, time_period
)

SELECT
    day_of_week,
    day_name,
    time_period,
    active_routes,
    total_observations,
    total_trips,
    network_avg_delay,
    network_on_time_pct,
    network_critical_count,
    network_severe_count,
    worst_delay_in_network,
    
    -- Network health score (0-100)
    ROUND(
        CAST(
            GREATEST(0, LEAST(100,
                network_on_time_pct * 0.6 +
                (100 - LEAST(network_avg_delay * 2, 50)) * 0.3 +
                (100 - LEAST(CAST(network_critical_count AS float) / NULLIF(total_trips, 0) * 1000, 50)) * 0.1
            ))
        AS numeric),
        2
    ) as network_health_score,
    
    -- Health classification
    CASE
        WHEN network_on_time_pct >= 80 AND network_avg_delay <= 5 THEN 'excellent'
        WHEN network_on_time_pct >= 70 AND network_avg_delay <= 10 THEN 'good'
        WHEN network_on_time_pct >= 60 AND network_avg_delay <= 15 THEN 'fair'
        WHEN network_on_time_pct >= 50 THEN 'poor'
        ELSE 'critical'
    END as network_health_status

FROM period_summary
ORDER BY day_of_week, 
    CASE time_period
        WHEN 'morning_rush' THEN 1
        WHEN 'off_peak' THEN 2
        WHEN 'lunch' THEN 3
        WHEN 'evening_rush' THEN 4
        WHEN 'night' THEN 5
    END