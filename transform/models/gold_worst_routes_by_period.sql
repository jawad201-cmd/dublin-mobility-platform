{{ config(materialized='table') }}

-- Identifies the best and worst performing routes by day of week and time period
-- Useful for: "Which routes are worst on Monday mornings?"

WITH route_period_stats AS (
    SELECT
        route_code,
        day_of_week,
        day_name,
        time_period,
        
        -- Aggregate metrics across all hours in this period
        COUNT(*) as observation_hours,
        SUM(total_observations) as total_observations,
        SUM(unique_trips) as total_trips,
        
        -- Weighted average delay (weighted by observations)
        ROUND(
            SUM(avg_delay_minutes * total_observations) / NULLIF(SUM(total_observations), 0),
            2
        ) as avg_delay,
        
        -- Average on-time percentage
        ROUND(AVG(on_time_percentage), 2) as avg_on_time_pct,
        
        -- Total problem counts
        SUM(critical_count) as total_critical_delays,
        SUM(severe_count) as total_severe_delays,
        SUM(moderate_count) as total_moderate_delays,
        
        -- Max delay seen in this period
        MAX(max_delay_minutes) as worst_delay_minutes
        
    FROM {{ ref('gold_route_performance_hourly') }}
    GROUP BY route_code, day_of_week, day_name, time_period
    HAVING COUNT(*) >= 2  -- At least 2 hours of data for reliability
),

ranked AS (
    SELECT
        *,
        -- Rank by worst delay (highest delay = rank 1)
        ROW_NUMBER() OVER (
            PARTITION BY day_of_week, time_period 
            ORDER BY avg_delay DESC
        ) as worst_rank,
        -- Rank by best performance (highest on-time % = rank 1)
        ROW_NUMBER() OVER (
            PARTITION BY day_of_week, time_period 
            ORDER BY avg_on_time_pct DESC
        ) as best_rank,
        -- Total routes in this period for context
        COUNT(*) OVER (PARTITION BY day_of_week, time_period) as total_routes_in_period
    FROM route_period_stats
)

SELECT 
    route_code,
    day_of_week,
    day_name,
    time_period,
    observation_hours,
    total_observations,
    total_trips,
    avg_delay,
    avg_on_time_pct,
    total_critical_delays,
    total_severe_delays,
    total_moderate_delays,
    worst_delay_minutes,
    worst_rank,
    best_rank,
    total_routes_in_period,
    
    -- Performance tier classification
    CASE 
        WHEN worst_rank <= 5 THEN 'worst_performer'
        WHEN best_rank <= 5 THEN 'best_performer'
        WHEN worst_rank <= total_routes_in_period * 0.25 THEN 'below_average'
        WHEN best_rank <= total_routes_in_period * 0.25 THEN 'above_average'
        ELSE 'average'
    END as performance_tier
    
FROM ranked
ORDER BY day_of_week, time_period, worst_rank