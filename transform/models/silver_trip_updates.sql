{{ config(materialized='incremental', unique_key='trip_id') }}

SELECT
    t.trip_id,
    t.route_id,
    (t.raw_data::jsonb ->> 'delay')::int as delay_seconds,
    t.raw_data::jsonb ->> 'stop_id' as stop_id,
    COALESCE(
        (SELECT MAX(TO_TIMESTAMP((v.raw_data::jsonb ->> 'timestamp')::bigint))
         FROM bronze_vehicle_positions v 
         WHERE v.trip_id = t.trip_id),
        NOW()
    ) as loaded_at

FROM bronze_trip_updates t
WHERE t.raw_data::jsonb ->> 'delay' IS NOT NULL

{% if is_incremental() %}
  AND t.trip_id NOT IN (SELECT trip_id FROM {{ this }})
{% endif %}