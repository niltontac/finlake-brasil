"""DAG de transformação Gold do domínio BCB — Banco Central do Brasil.

Executa modelos dbt Gold após conclusão de dag_silver_bcb via ExternalTaskSensor.
Downstream (Gold) aguarda upstream (Silver) — direção de dependência Data Mesh.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor

_DEFAULT_ARGS: dict = {
    "owner": "domain_bcb",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC_MD = """
## dag_gold_bcb

Transformação Gold do domínio BCB via dbt-core.

### Modelos executados

| Modelo          | Schema   | Grain   | Métricas                                                       |
|-----------------|----------|---------|----------------------------------------------------------------|
| `macro_mensal`  | gold_bcb | Mensal  | `selic_real`, `ptax_media`, `ptax_variacao_mensal_pct`         |
| `macro_diario`  | gold_bcb | Diário  | `selic_real` (diário), `acumulado_12m` carry forward           |

### Dependência cross-DAG

`wait_silver_bcb` usa `ExternalTaskSensor` aguardando `dag_silver_bcb` completar.
Downstream conhece upstream — princípio Data Mesh preservado.

### Selector dbt

`--select macro_mensal macro_diario` executa apenas os modelos Gold.
Silver não é re-executada — responsabilidade de `dag_silver_bcb`.
"""


@dag(
    dag_id="dag_gold_bcb",
    description="Gold BCB: métricas cross-série SELIC/IPCA/PTAX em gold_bcb via dbt",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["gold", "bcb", "domain_macro", "medallion", "dbt"],
    doc_md=_DOC_MD,
)
def dag_gold_bcb() -> None:
    """DAG de transformação Gold do domínio BCB."""

    wait_silver = ExternalTaskSensor(
        task_id="wait_silver_bcb",
        external_dag_id="dag_silver_bcb",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    dbt_run = BashOperator(
        task_id="dbt_run_gold_bcb",
        bash_command=(
            "dbt run"
            " --select macro_mensal macro_diario"
            " --target airflow"
            " --profiles-dir /opt/airflow/transform"
        ),
        cwd="/opt/airflow/transform",
    )

    wait_silver >> dbt_run


dag_gold_bcb()
