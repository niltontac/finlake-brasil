"""DAG de ingestão Bronze do domínio CVM — Cadastro de Fundos.

Ingestão diária do cad_fi.csv (CVM) para bronze_cvm.cadastro.
SCD Tipo 1: ON CONFLICT (cnpj_fundo) DO UPDATE.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.python import PythonOperator

from domain_cvm.ingestion.loaders_cadastro import ingest_cadastro

_DEFAULT_ARGS: dict = {
    "owner": "domain_cvm",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC_MD = """
## dag_bronze_cvm_cadastro

Ingestão diária do cadastro de fundos de investimento da CVM.

### Fonte

| Arquivo    | URL                                                       | Frequência |
|------------|-----------------------------------------------------------|------------|
| cad_fi.csv | https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv   | Diária     |

### Características

- ~30k fundos por arquivo
- Encoding ISO-8859-1 (latin1), separador ponto e vírgula
- SCD Tipo 1: `ON CONFLICT (cnpj_fundo) DO UPDATE` — espelha estado atual da CVM
- 40 colunas da fonte + `ingested_at`, `updated_at`, `source_url`

### Idempotência

Re-executar a DAG no mesmo dia atualiza `updated_at` para fundos modificados
e não duplica registros. `cnpj_fundo` é a PK.
"""


@dag(
    dag_id="dag_bronze_cvm_cadastro",
    description="Bronze CVM: cadastro de fundos diário (cad_fi.csv → bronze_cvm.cadastro)",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["bronze", "cvm", "domain_funds", "medallion"],
    doc_md=_DOC_MD,
)
def dag_bronze_cvm_cadastro() -> None:
    """DAG de ingestão do cadastro de fundos CVM."""

    PythonOperator(
        task_id="ingest_cadastro",
        python_callable=ingest_cadastro,
    )


dag_bronze_cvm_cadastro()
