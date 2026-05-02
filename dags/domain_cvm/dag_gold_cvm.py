"""DAG Gold CVM — métricas de performance de fundos via dbt."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor

_DEFAULT_ARGS = {
    "owner": "domain_funds",
    "retries": 3,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC_MD = """
## dag_gold_cvm

Transformação Gold do domínio Fundos (CVM) via dbt-core.

### Modelos executados

| Modelo          | Schema   | Grain              | Métricas principais                                    |
|-----------------|----------|--------------------|--------------------------------------------------------|
| `fundo_diario`  | gold_cvm | cnpj + dt_comptc   | `rentabilidade_diaria_pct` (LAG + NULLIF)              |
| `fundo_mensal`  | gold_cvm | cnpj + ano_mes     | `rentabilidade_mes_pct`, `alpha_selic`, `alpha_ipca`   |

### Dependências cross-DAG (paralelas)

- `wait_silver_cvm` → `dag_silver_cvm` (Silver CVM — fundos + informe_diario)
- `wait_gold_bcb`   → `dag_gold_bcb`   (Gold BCB — macro_mensal para cross-domain)

Ambos os sensores rodam em paralelo. `dbt_run_gold_cvm` aguarda os dois.
"""

_DBT_CMD = (
    "dbt run"
    " --select fundo_diario fundo_mensal"
    " --target airflow"
    " --profiles-dir /opt/airflow/transform"
)


@dag(
    dag_id="dag_gold_cvm",
    description="Gold CVM: métricas de performance e cross-domain BCB×CVM via dbt.",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["gold", "cvm", "domain_funds", "medallion", "dbt"],
    doc_md=_DOC_MD,
)
def dag_gold_cvm() -> None:
    """Orquestra a transformação Gold do domínio Fundos (CVM).

    Aguarda dag_silver_cvm e dag_gold_bcb em paralelo antes de executar
    os modelos dbt Gold (fundo_diario e fundo_mensal).
    """
    wait_silver_cvm = ExternalTaskSensor(
        task_id="wait_silver_cvm",
        external_dag_id="dag_silver_cvm",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    wait_gold_bcb = ExternalTaskSensor(
        task_id="wait_gold_bcb",
        external_dag_id="dag_gold_bcb",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    dbt_run_gold_cvm = BashOperator(
        task_id="dbt_run_gold_cvm",
        bash_command=_DBT_CMD,
        cwd="/opt/airflow/transform",
    )

    [wait_silver_cvm, wait_gold_bcb] >> dbt_run_gold_cvm


dag_gold_cvm()
