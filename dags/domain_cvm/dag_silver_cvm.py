"""DAG Silver CVM — transforma bronze_cvm em silver_cvm via dbt."""

from __future__ import annotations

from datetime import datetime

from airflow.decorators import dag
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor

_DEFAULT_ARGS = {
    "owner": "domain_funds",
    "retries": 1,
}

_DBT_CMD = (
    "dbt run"
    " --select domain_cvm"
    " --target airflow"
    " --profiles-dir /opt/airflow/transform"
)


@dag(
    dag_id="dag_silver_cvm",
    description="Silver CVM: transformação dbt de bronze_cvm em silver_cvm.",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["silver", "cvm", "domain_funds", "medallion", "dbt"],
)
def dag_silver_cvm() -> None:
    """Orquestra a transformação Silver do domínio Fundos (CVM).

    Aguarda a conclusão de dag_bronze_cvm_cadastro antes de executar
    os modelos dbt do domínio domain_cvm (fundos + informe_diario).
    """
    wait_bronze_cvm_cadastro = ExternalTaskSensor(
        task_id="wait_bronze_cvm_cadastro",
        external_dag_id="dag_bronze_cvm_cadastro",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    dbt_run_silver_cvm = BashOperator(
        task_id="dbt_run_silver_cvm",
        bash_command=_DBT_CMD,
        cwd="/opt/airflow/transform",
    )

    wait_bronze_cvm_cadastro >> dbt_run_silver_cvm


dag_silver_cvm()
