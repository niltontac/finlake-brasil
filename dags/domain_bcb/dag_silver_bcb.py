"""DAG de transformação Silver do domínio BCB — Banco Central do Brasil.

Executa modelos dbt após conclusão de dag_bronze_bcb via ExternalTaskSensor.
Downstream (Silver) aguarda upstream (Bronze) — direção de dependência Data Mesh.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor

_DEFAULT_ARGS: dict = {
    "owner": "domain_bcb",
    "retries": 3,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC_MD = """
## dag_silver_bcb

Transformação Silver do domínio BCB via dbt-core.

### Modelos executados

| Modelo            | Schema     | Coluna derivada       | Fórmula                                     |
|-------------------|------------|-----------------------|---------------------------------------------|
| `selic_daily`     | silver_bcb | `taxa_anual`          | `(1 + taxa_diaria/100)^252 - 1` em %       |
| `ipca_monthly`    | silver_bcb | `acumulado_12m`       | `EXP(SUM(LN()))` rolling 12 meses          |
| `ptax_daily`      | silver_bcb | `variacao_diaria_pct` | `(taxa_cambio / lag - 1) * 100`             |

### Dependência cross-DAG

`wait_bronze_bcb` usa `ExternalTaskSensor` aguardando `dag_bronze_bcb` completar.
Downstream conhece upstream — princípio Data Mesh preservado.

### NULLs esperados

- `acumulado_12m`: NULL de 1994-07 a 1995-05 (primeiros 11 meses, janela incompleta)
- `variacao_diaria_pct`: NULL apenas em 1999-01-04 (primeiro registro histórico)
"""


@dag(
    dag_id="dag_silver_bcb",
    description="Silver BCB: transformação dbt de SELIC, IPCA e PTAX para silver_bcb",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["silver", "bcb", "domain_macro", "medallion", "dbt"],
    doc_md=_DOC_MD,
)
def dag_silver_bcb() -> None:
    """DAG de transformação Silver do domínio BCB."""

    wait_bronze = ExternalTaskSensor(
        task_id="wait_bronze_bcb",
        external_dag_id="dag_bronze_bcb",
        external_task_id=None,
        timeout=3600,
        mode="reschedule",
        poke_interval=60,
    )

    dbt_run = BashOperator(
        task_id="dbt_run_silver_bcb",
        bash_command=(
            "dbt run"
            " --select domain_bcb"
            " --target airflow"
            " --profiles-dir /opt/airflow/transform"
        ),
        cwd="/opt/airflow/transform",
    )

    wait_bronze >> dbt_run


dag_silver_bcb()
