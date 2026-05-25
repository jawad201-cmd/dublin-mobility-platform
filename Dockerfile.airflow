FROM apache/airflow:2.7.1

# Switch to root to install git
USER root

# Run these one by one to avoid formatting errors
RUN apt-get update
RUN apt-get install -y git

# Switch back to airflow user
USER airflow

# Install Python libraries (added dbt-postgres)
RUN pip install --no-cache-dir \
    gtfs-realtime-bindings \
    requests \
    protobuf \
    pandas \
    psycopg2-binary \
    dbt-postgres==1.7.4