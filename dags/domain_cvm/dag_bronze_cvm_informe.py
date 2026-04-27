"""DAG de ingestão Bronze do domínio CVM — Informe Diário (delta mensal).

Processa sempre o mês anterior ao mês corrente.
PySpark (historical_load_cvm.py) é responsável pela carga histórica.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.python import PythonOperator

from domain_cvm.ingestion.loaders_informe import ingest_informe_mensal

_DEFAULT_ARGS: dict = {
    "owner": "domain_cvm",
    "retries": 2,
    "retry_delay": timedelta(minutes=15),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC_MD = """
## dag_bronze_cvm_informe

Ingestão mensal do informe diário de fundos de investimento da CVM.

### Fonte

| Arquivo                       | URL base                                          | Frequência |
|-------------------------------|---------------------------------------------------|------------|
| inf_diario_fi_YYYYMM.zip      | https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/ | Mensal     |

### Lógica de execução

- Processa sempre `mês corrente - 1` (mês anterior).
- O arquivo do mês N fica disponível na CVM no início de N+1.
- `catchup=False`: histórico é carregado via PySpark (`make cvm-hist-load`).

### Idempotência

`ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING` — re-executar é seguro
e não duplica registros.

### Colunas

`TP_FUNDO`, `CNPJ_FUNDO`, `DT_COMPTC`, `VL_TOTAL`, `VL_QUOTA`,
`VL_PATRIM_LIQ`, `CAPTC_DIA`, `RESG_DIA`, `NR_COTST` + `ingested_at`, `source_url`.
"""


@dag(
    dag_id="dag_bronze_cvm_informe",
    description="Bronze CVM: informe diário mensal (ZIP → bronze_cvm.informe_diario)",
    schedule="@monthly",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["bronze", "cvm", "domain_funds", "medallion"],
    doc_md=_DOC_MD,
)
def dag_bronze_cvm_informe() -> None:
    """DAG de ingestão do informe diário de fundos CVM."""

    PythonOperator(
        task_id="ingest_informe_mensal",
        python_callable=ingest_informe_mensal,
    )


dag_bronze_cvm_informe()
