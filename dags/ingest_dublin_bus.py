from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from airflow.models import Variable
from airflow.utils.dates import days_ago
from google.transit import gtfs_realtime_pb2
import requests
import json
import pandas as pd
from sqlalchemy import create_engine

# CONFIGURATION
API_KEY = Variable.get("NTA_API_KEY")
DB_CONN = "postgresql+psycopg2://airflow:airflow@postgres/mobility_db"

URL_VEHICLES = "https://api.nationaltransport.ie/gtfsr/v2/Vehicles?format=pb"
URL_TRIPS = "https://api.nationaltransport.ie/gtfsr/v2/TripUpdates?format=pb"

# Path to dbt project inside the container
DBT_PROJECT_DIR = "/opt/airflow/dbt"


def extract_and_load(url, entity_type, table_name, **context):
    print(f"Starting Pipeline for {entity_type}...")
    
    # 1. EXTRACT
    headers = {"x-api-key": API_KEY, "Cache-Control": "no-cache"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"API Connection Failed: {e}")
        raise

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(response.content)
    
    parsed_data = []
    
    # 2. TRANSFORM
    for entity in feed.entity:
        # LOGIC FOR VEHICLES
        if entity_type == 'vehicle' and entity.HasField('vehicle'):
            v = entity.vehicle
            if v.trip.trip_id:
                row = {
                    "vehicle_id": entity.id,
                    "trip_id": v.trip.trip_id,
                    "raw_data": json.dumps({
                        "lat": v.position.latitude,
                        "lon": v.position.longitude,
                        "route_id": v.trip.route_id,
                        "timestamp": v.timestamp
                    })
                }
                parsed_data.append(row)

        # LOGIC FOR TRIP UPDATES (DELAYS)
        elif entity_type == 'trip_update' and entity.HasField('trip_update'):
            t = entity.trip_update
            if len(t.stop_time_update) > 0:
                stu = t.stop_time_update[0]
                if stu.HasField('arrival'):
                    delay = stu.arrival.delay
                elif stu.HasField('departure'):
                    delay = stu.departure.delay
                else:
                    delay = 0

                row = {
                    "trip_id": t.trip.trip_id,
                    "route_id": t.trip.route_id,
                    "raw_data": json.dumps({
                        "delay": delay,
                        "stop_id": stu.stop_id
                    })
                }
                parsed_data.append(row)

    print(f"Parsed {len(parsed_data)} records.")

    # 3. LOAD
    if len(parsed_data) > 0:
        df = pd.DataFrame(parsed_data)
        engine = create_engine(DB_CONN)
        df.to_sql(table_name, engine, if_exists='append', index=False)
        print(f"Successfully loaded {len(parsed_data)} rows to {table_name}")
    else:
        print("No data found to load.")


# DAG DEFINITION
with DAG(
    dag_id='dublin_mobility_ETL_v1',
    default_args={'owner': 'airflow', 'retries': 1},
    schedule_interval='*/5 * * * *',
    start_date=days_ago(1),
    catchup=False,
    tags=['dublin', 'mobility', 'etl']
) as dag:

    # Task 1: Extract and load vehicle positions
    task_vehicles = PythonOperator(
        task_id='etl_vehicles',
        python_callable=extract_and_load,
        op_kwargs={
            'url': URL_VEHICLES,
            'entity_type': 'vehicle',
            'table_name': 'bronze_vehicle_positions'
        },
        provide_context=True
    )

    # Task 2: Extract and load trip updates (delays)
    task_trips = PythonOperator(
        task_id='etl_trip_updates',
        python_callable=extract_and_load,
        op_kwargs={
            'url': URL_TRIPS,
            'entity_type': 'trip_update',
            'table_name': 'bronze_trip_updates'
        },
        provide_context=True
    )

    # Task 3: Run dbt to transform bronze → silver → gold
    task_dbt_run = BashOperator(
        task_id='dbt_run',
        bash_command=f'cd {DBT_PROJECT_DIR} && dbt deps --log-path /tmp/dbt_logs && dbt run --profiles-dir {DBT_PROJECT_DIR} --log-path /tmp/dbt_logs',
    )

    # Define task dependencies
    # Both ETL tasks run in parallel, then dbt runs after both complete
    [task_vehicles, task_trips] >> task_dbt_run