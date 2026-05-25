{{ config(materialized='incremental', unique_key='vehicle_id') }}

SELECT
    vehicle_id,
    trip_id,
    (raw_data::jsonb ->> 'lat')::float as latitude,
    (raw_data::jsonb ->> 'lon')::float as longitude,
    raw_data::jsonb ->> 'route_id' as route_id,
    TO_TIMESTAMP((raw_data::jsonb ->> 'timestamp')::bigint) as gps_timestamp,
    TO_TIMESTAMP((raw_data::jsonb ->> 'timestamp')::bigint) as loaded_at

FROM bronze_vehicle_positions
WHERE raw_data::jsonb ->> 'lat' IS NOT NULL

{% if is_incremental() %}
  AND TO_TIMESTAMP((raw_data::jsonb ->> 'timestamp')::bigint) > (SELECT MAX(loaded_at) FROM {{ this }})
{% endif %}