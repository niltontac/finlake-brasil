"""DAG de ingestão Bronze do domínio BCB — Banco Central do Brasil.

Ingestão de SELIC, IPCA e PTAX via python-bcb para o schema bronze_bcb
no PostgreSQL. Tasks paralelas e independentes com smart first run.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.python import PythonOperator

from domain_bcb.ingestion.loaders import ingest_ipca, ingest_ptax, ingest_selic

_DEFAULT_ARGS: dict = {
    "owner": "domain_bcb",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC_MD = """
## dag_bronze_bcb

Ingestão da camada Bronze do domínio BCB (Banco Central do Brasil).

### Séries ingeridas

| Task                 | Série  | Código BCB | Frequência | Backfill desde |
|----------------------|--------|------------|------------|----------------|
| ingest_selic_daily   | SELIC  | 11         | Diária     | 2000-01-01     |
| ingest_ipca_monthly  | IPCA   | 433        | Mensal     | 1994-07-01     |
| ingest_ptax_daily    | PTAX   | 1          | Diária     | 1999-01-01     |

### Smart first run

Na primeira execução, cada task detecta tabela vazia e executa backfill completo
desde a `start_date` da série. Execuções subsequentes carregam apenas o delta.

### Idempotência

`INSERT ... ON CONFLICT (date) DO NOTHING` — reprocessar a DAG no mesmo dia
é seguro e não duplica registros.

### Tasks em paralelo

As 3 tasks são independentes: falha em uma não cancela as demais.

### IPCA como Skipped

A task `ingest_ipca_monthly` aparecerá como **Skipped** (amarelo) na maioria
dos dias do mês — comportamento esperado, pois o dado mensal já foi gravado.
"""


@dag(
    dag_id="dag_bronze_bcb",
    description="Bronze BCB: ingestão de SELIC, IPCA e PTAX via python-bcb",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["bronze", "bcb", "domain_macro", "medallion"],
    doc_md=_DOC_MD,
)
def dag_bronze_bcb() -> None:
    """DAG de ingestão Bronze do domínio BCB."""

    PythonOperator(
        task_id="ingest_selic_daily",
        python_callable=ingest_selic,
    )

    PythonOperator(
        task_id="ingest_ipca_monthly",
        python_callable=ingest_ipca,
    )

    PythonOperator(
        task_id="ingest_ptax_daily",
        python_callable=ingest_ptax,
    )


dag_bronze_bcb()
