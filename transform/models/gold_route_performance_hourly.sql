{{ config(
    materialized='incremental',
    unique_key='performance_id',
    on_schema_change='append_new_columns'
) }}

-- Hourly aggregated performance metrics per route
-- Used for trend analysis and historical reporting

WITH hourly_stats AS (
    SELECT
        -- Create unique ID for each hour/route combination
        {{ dbt_utils.generate_surrogate_key(['route_code', 'record_date', 'record_hour']) }} as performance_id,
        
        route_code,
        record_date,
        record_hour,
        day_of_week,
        day_name,
        time_period,
        
        -- Volume metrics
        COUNT(*) as total_observations,
        COUNT(DISTINCT trip_id) as unique_trips,
        
        -- Delay metrics (cast to numeric for ROUND function)
        ROUND(AVG(delay_minutes)::numeric, 2) as avg_delay_minutes,
        ROUND(CAST(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY delay_minutes) AS numeric), 2) as median_delay_minutes,
        ROUND(MAX(delay_minutes)::numeric, 2) as max_delay_minutes,
        ROUND(MIN(delay_minutes)::numeric, 2) as min_delay_minutes,
        ROUND(COALESCE(STDDEV(delay_minutes)::numeric, 0), 2) as stddev_delay_minutes,
        
        -- Category counts
        COUNT(CASE WHEN delay_category = 'early' THEN 1 END) as early_count,
        COUNT(CASE WHEN delay_category = 'on_time' THEN 1 END) as on_time_count,
        COUNT(CASE WHEN delay_category = 'minor' THEN 1 END) as minor_count,
        COUNT(CASE WHEN delay_category = 'moderate' THEN 1 END) as moderate_count,
        COUNT(CASE WHEN delay_category = 'severe' THEN 1 END) as severe_count,
        COUNT(CASE WHEN delay_category = 'critical' THEN 1 END) as critical_count,
        
        -- Performance score (% on-time or early)
        ROUND(
            CAST(100.0 * COUNT(CASE WHEN delay_category IN ('early', 'on_time') THEN 1 END) / NULLIF(COUNT(*), 0) AS numeric),
            2
        ) as on_time_percentage,
        
        -- Timestamp for incremental loading
        MAX(recorded_at) as last_updated
        
    FROM {{ ref('fact_historical_delays') }}
    
    {% if is_incremental() %}
        WHERE recorded_at > (SELECT COALESCE(MAX(last_updated), '1900-01-01'::timestamp) FROM {{ this }})
    {% endif %}
    
    GROUP BY 
        route_code, 
        record_date, 
        record_hour, 
        day_of_week, 
        day_name, 
        time_period
)

SELECT * FROM hourly_stats