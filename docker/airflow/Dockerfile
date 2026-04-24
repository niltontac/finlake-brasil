FROM apache/airflow:2.10.4-python3.12

ARG AIRFLOW_VERSION=2.10.4
ARG PYTHON_VERSION=3.12
ARG CONSTRAINT_URL="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

USER airflow

COPY docker/airflow/requirements.txt /opt/airflow/requirements.txt

RUN pip install --no-cache-dir \
    -r /opt/airflow/requirements.txt \
    --constraint "${CONSTRAINT_URL}"

RUN pip install --no-cache-dir dbt-postgres
