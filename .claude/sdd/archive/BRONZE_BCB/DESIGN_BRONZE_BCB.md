# DESIGN: Bronze BCB — Ingestão de Séries Temporais do Banco Central

> Design técnico para ingestão idempotente de SELIC, IPCA e PTAX do BCB
> na camada Bronze com smart first run via DAG Airflow.

## Metadata

| Atributo    | Valor                                                                    |
|-------------|--------------------------------------------------------------------------|
| **Feature** | BRONZE_BCB                                                               |
| **Data**    | 2026-04-23                                                               |
| **Autor**   | Nilton Coura                                                             |
| **DEFINE**  | [DEFINE_BRONZE_BCB.md](./DEFINE_BRONZE_BCB.md)                          |
| **Status**  | ✅ Shipped                                                               |

---

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                     dag_bronze_bcb  (schedule: @daily)                   │
│                                                                           │
│   Airflow Scheduler                                                       │
│         │                                                                 │
│   ┌─────┴──────────────────────────────────────────┐                    │
│   │                (tasks em paralelo)              │                    │
│   ▼                       ▼                         ▼                    │
│ ┌────────────────┐  ┌─────────────────┐  ┌──────────────────┐           │
│ │ingest_selic_   │  │ingest_ipca_     │  │ingest_ptax_      │           │
│ │daily           │  │monthly          │  │daily             │           │
│ │(PythonOperator)│  │(PythonOperator) │  │(PythonOperator)  │           │
│ └───────┬────────┘  └────────┬────────┘  └────────┬─────────┘           │
└─────────┼────────────────────┼────────────────────┼─────────────────────┘
          │                    │                     │
          └────────────────────┼─────────────────────┘
                               │ (todas chamam)
                 ┌─────────────┴──────────────────────┐
                 │  dags/domain_bcb/ingestion/          │
                 │                                      │
                 │  loaders.py                          │
                 │    ingest_selic()                    │
                 │    ingest_ipca()                     │
                 │    ingest_ptax()                     │
                 │    _upsert_dataframe()               │
                 │                                      │
                 │  bcb_client.py                       │
                 │    SERIES_CONFIG                     │
                 │    get_load_range()                  │
                 │    fetch_series()                    │
                 └─────────────┬──────────────────────┘
                               │
               ┌───────────────┴────────────────┐
               │                                │
               ▼                                ▼
  ┌────────────────────────┐    ┌─────────────────────────────────────┐
  │  BCB SGS API (REST)    │    │  PostgreSQL 15                      │
  │  dadosabertos.bcb.gov.br│    │  host: postgres:5432  (Docker net) │
  │  Séries:               │    │  db: finlake                        │
  │    SELIC → 11          │    │  schema: bronze_bcb                 │
  │    IPCA  → 433         │    │    selic_daily                      │
  │    PTAX  → 1           │    │    ipca_monthly                     │
  │  via python-bcb        │    │    ptax_daily                       │
  └────────────────────────┘    └─────────────────────────────────────┘
```

---

## Components

| Componente                                    | Propósito                                                           | Tecnologia                        |
|-----------------------------------------------|---------------------------------------------------------------------|-----------------------------------|
| `dag_bronze_bcb.py`                           | Definição da DAG, schedule, default_args, 3 tasks paralelas         | Airflow DAG + PythonOperator      |
| `ingestion/bcb_client.py`                     | `SERIES_CONFIG`, `get_load_range()`, `fetch_series()` — wrapper BCB | python-bcb, psycopg2 via hook     |
| `ingestion/loaders.py`                        | Funções de ingestão por série + `_upsert_dataframe()` compartilhado | pandas, PostgresHook              |
| `migrations/001_bronze_bcb.sql`               | DDL: schema `bronze_bcb` + 3 tabelas com PKs e defaults             | SQL puro                          |
| `compose.airflow.yml` (modificação)           | Injeta `AIRFLOW_CONN_FINLAKE_POSTGRES` no container                 | Docker Compose                    |
| `requirements.txt` (modificação)             | Adiciona `apache-airflow-providers-postgres` à imagem               | pip + constraints Airflow 2.10.4  |

---

## Key Decisions (ADRs)

### ADR-001: `catchup=False` + smart first run vs. Airflow catchup nativo

| Atributo   | Valor                |
|------------|----------------------|
| **Status** | Accepted             |
| **Data**   | 2026-04-23           |

**Context:** O backfill histórico precisa ser resolvido na primeira execução da DAG.
Airflow oferece `catchup=True` nativo, que cria um run por intervalo desde `start_date`.

**Choice:** `catchup=False` na DAG + lógica `get_load_range()` que detecta tabela
vazia e carrega o range histórico completo numa única execução.

**Rationale:** Catchup nativo criaria milhares de runs (um por dia desde 2000),
sobrecarregando o Airflow scheduler e a API BCB com requests sequenciais sem
controle de rate. Smart first run executa uma única chamada à API com o range
completo, que é o padrão suportado pelo `python-bcb`.

**Alternativas rejeitadas:**
1. `catchup=True` com `start_date=2000-01-01` — cria ~9.000 runs históricos,
   scheduler LocalExecutor não suporta esse volume sem degradação.
2. Script de backfill separado — fragmenta a responsabilidade; a DAG deixaria de
   ser autossuficiente no primeiro `trigger`.

**Consequências:**
- Primeira execução é mais longa (bulk load de ~6.500+ registros por série).
- Airflow mostrará apenas um run bem-sucedido na primeira execução.
- Execuções posteriores são rápidas (delta do dia).

---

### ADR-002: `SERIES_CONFIG` centralizado vs. parâmetros hardcoded por função

| Atributo   | Valor                |
|------------|----------------------|
| **Status** | Accepted             |
| **Data**   | 2026-04-23           |

**Context:** As 3 séries compartilham o mesmo padrão de ingestão (fetch → upsert),
diferindo apenas em código BCB, `start_date` e frequência.

**Choice:** Dict `SERIES_CONFIG` em `bcb_client.py` como fonte única de verdade
para todos os parâmetros por série.

**Rationale:** Adicionar uma quarta série (ex: CDI, TJLP) requer apenas uma entrada
no dict e uma nova função de loader de 5 linhas. Sem `SERIES_CONFIG`, cada nova
série duplica a lógica de `get_load_range()` e os parâmetros BCB em 3 lugares.

**Alternativas rejeitadas:**
1. `Airflow Variables` para `start_date` — over-engineering para MVP; o dict é
   suficiente e versionável no código.
2. YAML externo de configuração — desnecessário na escala atual.

**Consequências:**
- Única fonte de verdade: mudar o código de série BCB ou `start_date` requer
  alteração em um único lugar.
- Testável diretamente — o dict é importável sem dependências de runtime.

---

### ADR-003: `AirflowSkipException` para "nada a fazer" vs. `return` silencioso

| Atributo   | Valor                |
|------------|----------------------|
| **Status** | Accepted             |
| **Data**   | 2026-04-23           |

**Context:** Quando `get_load_range()` retorna `None` (tabela já atualizada ou
IPCA do mês já gravado), a task não tem trabalho a fazer.

**Choice:** Lançar `AirflowSkipException` em vez de retornar silenciosamente.

**Rationale:** `AirflowSkipException` marca a task como `Skipped` (amarelo) na
UI do Airflow, tornando explícito que a task rodou e decidiu não fazer nada.
Um `return` silencioso marcaria a task como `Success` (verde), indistinguível
de uma task que realmente inseriu dados — perda de observabilidade.

**Alternativas rejeitadas:**
1. `return None` silencioso — task aparece como `Success` mesmo sem inserir nada.
2. `AirflowSensorTimeout` — semântica errada; é para sensores, não para loaders.

**Consequências:**
- IPCA aparecerá como `Skipped` na maioria dos dias do mês na UI.
- Operadores podem confundir `Skipped` com problema; deve ser documentado no
  `doc_md` da DAG.

---

### ADR-004: `_upsert_dataframe()` com `executemany` vs. `COPY FROM`

| Atributo   | Valor                |
|------------|----------------------|
| **Status** | Accepted             |
| **Data**   | 2026-04-23           |

**Context:** Inserção dos registros do DataFrame no PostgreSQL com idempotência.

**Choice:** `cursor.executemany()` com `INSERT ... ON CONFLICT (date) DO NOTHING`.

**Rationale:** O volume máximo por run é ~6.500 registros (backfill completo
SELIC). `executemany` com psycopg2 é adequado para este volume. `COPY FROM`
seria mais performático, mas não suporta `ON CONFLICT` nativamente — precisaria
de tabela staging + MERGE, adicionando complexidade desnecessária.

**Alternativas rejeitadas:**
1. `DataFrame.to_sql(if_exists='append')` — sem controle de conflito; duplicatas
   em reprocessamento. Descartado no Brainstorm.
2. `COPY FROM` + staging table — mais rápido para volumes > 100k linhas, mas
   complexidade injustificada para <7k registros.

**Consequências:**
- Aceitamos performance ligeiramente inferior ao `COPY` para ganhar simplicidade.
- Em caso de volume > 50k registros (improvável no BCB), revisitar para `COPY`.

---

### ADR-005: Versão do provider gerenciada por constraints do Airflow

| Atributo   | Valor                |
|------------|----------------------|
| **Status** | Accepted             |
| **Data**   | 2026-04-23           |

**Context:** A suposição A-005 do DEFINE: compatibilidade de
`apache-airflow-providers-postgres` com Airflow 2.10.4.

**Choice:** Adicionar o provider sem versão fixa em `requirements.txt`; deixar
o arquivo de constraints do Airflow 2.10.4 resolver a versão compatível.

**Rationale:** O `Dockerfile` já usa o constraints URL oficial
(`constraints-2.10.4/constraints-3.12.txt`). Este arquivo pina todas as
dependências do ecossistema Airflow em versões testadas e compatíveis entre si.
Fixar manualmente cria risco de conflito com o constraints file.

**Alternativas rejeitadas:**
1. Versão fixada manualmente (ex: `==5.12.0`) — pode conflitar com o constraints
   file do Airflow e causar erros de build da imagem.

**Consequências:**
- Versão resolvida automaticamente pelo constraints file no build da imagem.
- Auditável via `pip freeze` dentro do container após build.

---

## File Manifest

| #  | Arquivo                                              | Ação     | Propósito                                              | Dependências |
|----|------------------------------------------------------|----------|--------------------------------------------------------|--------------|
| 1  | `docker/postgres/migrations/001_bronze_bcb.sql`      | Create   | DDL: schema `bronze_bcb` + 3 tabelas                  | —            |
| 2  | `docker/airflow/requirements.txt`                    | Modify   | Adicionar `apache-airflow-providers-postgres`          | —            |
| 3  | `.env.example`                                       | Modify   | Adicionar `AIRFLOW_CONN_FINLAKE_POSTGRES` com template | —            |
| 4  | `docker/compose.airflow.yml`                         | Modify   | Injetar `AIRFLOW_CONN_FINLAKE_POSTGRES` no container  | —            |
| 5  | `dags/domain_bcb/__init__.py`                        | Create   | Pacote Python do domínio BCB                          | —            |
| 6  | `dags/domain_bcb/ingestion/__init__.py`              | Create   | Sub-pacote de ingestão                                | 5            |
| 7  | `dags/domain_bcb/ingestion/bcb_client.py`            | Create   | `SERIES_CONFIG`, `get_load_range()`, `fetch_series()` | 6            |
| 8  | `dags/domain_bcb/ingestion/loaders.py`               | Create   | `ingest_selic/ipca/ptax()`, `_upsert_dataframe()`     | 6, 7         |
| 9  | `dags/domain_bcb/dag_bronze_bcb.py`                  | Create   | Definição da DAG + 3 PythonOperators                  | 5, 8         |
| 10 | `tests/__init__.py`                                  | Create   | Pacote raiz de testes                                 | —            |
| 11 | `tests/domain_bcb/__init__.py`                       | Create   | Pacote de testes do domínio BCB                       | 10           |
| 12 | `tests/domain_bcb/test_bcb_client.py`                | Create   | Unit tests: `get_load_range()` — 5 cenários           | 7, 11        |
| 13 | `tests/domain_bcb/test_loaders.py`                   | Create   | Unit tests: loaders com PostgresHook mockado          | 8, 11        |

**Total de arquivos:** 13 (4 modificações de infraestrutura + 9 novos)

---

## Agent Assignment Rationale

| Agente                  | Arquivos  | Justificativa                                                      |
|-------------------------|-----------|--------------------------------------------------------------------|
| @airflow-specialist     | 9         | DAG design, PythonOperator, catchup, trigger_rule, default_args   |
| @python-developer       | 7, 8      | Type hints, dataclasses, PEP8, tratamento de DataFrame             |
| @test-generator         | 12, 13    | pytest fixtures, mock de hook, cenários de edge case              |
| (general / build-agent) | 1–6, 10, 11 | SQL DDL, requirements.txt, compose YAML, __init__.py vazios      |

---

## Code Patterns

### Pattern 1: `SERIES_CONFIG` — configuração centralizada por série

```python
# dags/domain_bcb/ingestion/bcb_client.py
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from bcb import sgs

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SeriesConfig:
    """Configuração imutável de uma série temporal BCB."""

    name: str
    code: int
    start_date: date
    table: str
    frequency: str  # "daily" | "monthly"
    value_column: str


SERIES_CONFIG: dict[str, SeriesConfig] = {
    "selic_daily": SeriesConfig(
        name="SELIC",
        code=11,
        start_date=date(2000, 1, 1),
        table="bronze_bcb.selic_daily",
        frequency="daily",
        value_column="SELIC",
    ),
    "ipca_monthly": SeriesConfig(
        name="IPCA",
        code=433,
        start_date=date(1994, 7, 1),
        table="bronze_bcb.ipca_monthly",
        frequency="monthly",
        value_column="IPCA",
    ),
    "ptax_daily": SeriesConfig(
        name="PTAX",
        code=1,
        start_date=date(1999, 1, 1),
        table="bronze_bcb.ptax_daily",
        frequency="daily",
        value_column="PTAX",
    ),
}
```

---

### Pattern 2: `get_load_range()` — smart first run + delta incremental

```python
# dags/domain_bcb/ingestion/bcb_client.py  (continuação)
from airflow.providers.postgres.hooks.postgres import PostgresHook


def get_load_range(
    config: SeriesConfig,
    hook: PostgresHook,
) -> Optional[tuple[date, date]]:
    """Determina o intervalo de datas a carregar.

    Retorna:
        (start, end): intervalo para carga (backfill ou delta).
        None: tabela já atualizada ou mês IPCA já gravado (skip).
    """
    today = date.today()

    row = hook.get_first(f"SELECT MAX(date) FROM {config.table}")
    max_date: Optional[date] = row[0] if row and row[0] else None

    if max_date is None:
        logger.info(
            "%s: tabela vazia — backfill desde %s até %s",
            config.name, config.start_date, today,
        )
        return (config.start_date, today)

    if config.frequency == "monthly":
        current_month_start = today.replace(day=1)
        if max_date >= current_month_start:
            logger.info("%s: mês %s já gravado — skip.", config.name, current_month_start)
            return None

    next_date = max_date + timedelta(days=1)
    if next_date > today:
        logger.info("%s: já atualizado até %s — skip.", config.name, max_date)
        return None

    logger.info("%s: delta de %s até %s.", config.name, next_date, today)
    return (next_date, today)


def fetch_series(config: SeriesConfig, start: date, end: date) -> pd.DataFrame:
    """Busca série temporal na API SGS do BCB.

    Retorna DataFrame com DatetimeIndex e coluna `config.value_column`.
    Pode retornar DataFrame vazio se não houver dados no intervalo (ex: feriados).
    """
    df: pd.DataFrame = sgs.get({config.value_column: config.code}, start=start, end=end)
    logger.info("%s: %d registros obtidos da API BCB.", config.name, len(df))
    return df
```

---

### Pattern 3: `_upsert_dataframe()` + loader por série

```python
# dags/domain_bcb/ingestion/loaders.py
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
from airflow.exceptions import AirflowSkipException
from airflow.providers.postgres.hooks.postgres import PostgresHook

from domain_bcb.ingestion.bcb_client import SERIES_CONFIG, fetch_series, get_load_range

logger = logging.getLogger(__name__)

CONN_ID = "finlake_postgres"

_UPSERT_SQL = "INSERT INTO {table} (date, valor) VALUES (%s, %s) ON CONFLICT (date) DO NOTHING"


def _upsert_dataframe(hook: PostgresHook, config, df: pd.DataFrame) -> int:
    """Insere registros do DataFrame com idempotência. Retorna nº de linhas processadas."""
    if df.empty:
        logger.warning("%s: DataFrame vazio, nenhum registro para inserir.", config.name)
        return 0

    rows: list[tuple[date, float]] = [
        (idx.date(), float(val))
        for idx, val in zip(df.index, df[config.value_column])
        if pd.notna(val)
    ]

    if not rows:
        return 0

    conn = hook.get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL.format(table=config.table), rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        hook.return_conn(conn)

    logger.info("%s: %d registros processados (ON CONFLICT DO NOTHING ativo).", config.name, len(rows))
    return len(rows)


def _ingest_series(series_key: str) -> None:
    """Função genérica de ingestão — usada pelos loaders específicos."""
    config = SERIES_CONFIG[series_key]
    hook = PostgresHook(postgres_conn_id=CONN_ID)

    load_range = get_load_range(config, hook)
    if load_range is None:
        raise AirflowSkipException(f"{config.name}: nada a carregar.")

    start, end = load_range
    df = fetch_series(config, start, end)
    _upsert_dataframe(hook, config, df)


def ingest_selic(**kwargs) -> None:
    """Task Airflow: ingestão diária da SELIC (série BCB 11)."""
    _ingest_series("selic_daily")


def ingest_ipca(**kwargs) -> None:
    """Task Airflow: ingestão mensal do IPCA (série BCB 433)."""
    _ingest_series("ipca_monthly")


def ingest_ptax(**kwargs) -> None:
    """Task Airflow: ingestão diária da PTAX venda (série BCB 1)."""
    _ingest_series("ptax_daily")
```

---

### Pattern 4: DAG definition

```python
# dags/domain_bcb/dag_bronze_bcb.py
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag
from airflow.operators.python import PythonOperator

from domain_bcb.ingestion.loaders import ingest_ipca, ingest_ptax, ingest_selic

_DEFAULT_ARGS = {
    "owner": "domain_bcb",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
    "email_on_retry": False,
}

_DOC = """
## dag_bronze_bcb

Ingestão da camada Bronze do domínio BCB (Banco Central do Brasil).

### Séries ingeridas
| Task                  | Série BCB | Código | Frequência |
|-----------------------|-----------|--------|------------|
| ingest_selic_daily    | SELIC     | 11     | Diária     |
| ingest_ipca_monthly   | IPCA      | 433    | Mensal     |
| ingest_ptax_daily     | PTAX venda| 1      | Diária     |

### Smart first run
Na primeira execução, cada task detecta tabela vazia e executa backfill completo
desde a `start_date` da série. Execuções subsequentes carregam apenas o delta.

### Idempotência
`INSERT ... ON CONFLICT (date) DO NOTHING` — reprocessamento é sempre seguro.

### Tasks em paralelo
As 3 tasks são independentes: falha em uma não cancela as demais.
Task `ingest_ipca_monthly` aparecerá como `Skipped` na maioria dos dias do mês
(comportamento esperado — mês já gravado).
"""


@dag(
    dag_id="dag_bronze_bcb",
    description="Bronze BCB: ingestão de SELIC, IPCA e PTAX via python-bcb",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["bronze", "bcb", "domain_macro", "medallion"],
    doc_md=_DOC,
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
    # Sem dependências entre tasks — executam em paralelo por design


dag_bronze_bcb()
```

---

### Pattern 5: Migration SQL

```sql
-- docker/postgres/migrations/001_bronze_bcb.sql
-- Domínio BCB — schema e tabelas Bronze
-- Execute: psql -U postgres -d finlake -f 001_bronze_bcb.sql

CREATE SCHEMA IF NOT EXISTS bronze_bcb;

COMMENT ON SCHEMA bronze_bcb IS
    'Bronze layer — domínio BCB (Banco Central do Brasil). '
    'Dados brutos sem transformação, particionados por data de referência.';

CREATE TABLE IF NOT EXISTS bronze_bcb.selic_daily (
    date        DATE          NOT NULL,
    valor       NUMERIC(10,6) NOT NULL,
    ingested_at TIMESTAMP     NOT NULL DEFAULT NOW(),
    source_api  VARCHAR(50)   NOT NULL DEFAULT 'BCB_SGS',
    CONSTRAINT selic_daily_pkey PRIMARY KEY (date)
);

COMMENT ON TABLE  bronze_bcb.selic_daily IS 'SELIC over (diária) — série BCB SGS 11';
COMMENT ON COLUMN bronze_bcb.selic_daily.date  IS 'Data de referência (dias úteis)';
COMMENT ON COLUMN bronze_bcb.selic_daily.valor IS 'Taxa SELIC (% a.d., 6 casas decimais)';

CREATE TABLE IF NOT EXISTS bronze_bcb.ipca_monthly (
    date        DATE         NOT NULL,
    valor       NUMERIC(6,4) NOT NULL,
    ingested_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    source_api  VARCHAR(50)  NOT NULL DEFAULT 'BCB_SGS',
    CONSTRAINT ipca_monthly_pkey PRIMARY KEY (date)
);

COMMENT ON TABLE  bronze_bcb.ipca_monthly IS 'IPCA (mensal) — série BCB SGS 433';
COMMENT ON COLUMN bronze_bcb.ipca_monthly.date  IS 'Primeiro dia do mês de referência';
COMMENT ON COLUMN bronze_bcb.ipca_monthly.valor IS 'Variação mensal do IPCA (%, 4 casas decimais)';

CREATE TABLE IF NOT EXISTS bronze_bcb.ptax_daily (
    date        DATE          NOT NULL,
    valor       NUMERIC(10,4) NOT NULL,
    ingested_at TIMESTAMP     NOT NULL DEFAULT NOW(),
    source_api  VARCHAR(50)   NOT NULL DEFAULT 'BCB_SGS',
    CONSTRAINT ptax_daily_pkey PRIMARY KEY (date)
);

COMMENT ON TABLE  bronze_bcb.ptax_daily IS 'PTAX venda USD/BRL (diária) — série BCB SGS 1';
COMMENT ON COLUMN bronze_bcb.ptax_daily.date  IS 'Data de referência (dias úteis)';
COMMENT ON COLUMN bronze_bcb.ptax_daily.valor IS 'Taxa PTAX venda (R$/USD, 4 casas decimais)';
```

---

### Pattern 6: Modificações de infraestrutura

**`docker/airflow/requirements.txt`** — adicionar provider:
```
apache-airflow-providers-postgres
```

**`.env.example`** — adicionar connection string:
```dotenv
# ------------------------------------------------------------
# Airflow Connections
# Host interno Docker: 'postgres' (não localhost)
# Porta interna Docker: 5432 (não 5433)
# ------------------------------------------------------------
AIRFLOW_CONN_FINLAKE_POSTGRES=postgresql://postgres:<POSTGRES_PASSWORD>@postgres:5432/finlake
```

**`docker/compose.airflow.yml`** — adicionar na seção `environment`:
```yaml
AIRFLOW_CONN_FINLAKE_POSTGRES: "${AIRFLOW_CONN_FINLAKE_POSTGRES}"
```

---

## Data Flow

```text
1. Airflow Scheduler dispara dag_bronze_bcb (@daily)
   │
   ├─▶ 2a. ingest_selic_daily / ingest_ptax_daily
   │       │
   │       ├─▶ PostgresHook → SELECT MAX(date) FROM bronze_bcb.*_daily
   │       │     • Vazio    → start_date configurado (backfill)
   │       │     • Com dado → max_date + 1 dia (delta)
   │       │     • Hoje     → AirflowSkipException
   │       │
   │       ├─▶ bcb.sgs.get({série: código}, start, end)
   │       │     Retorna DataFrame(DatetimeIndex, float64)
   │       │
   │       └─▶ executemany: INSERT ... ON CONFLICT (date) DO NOTHING
   │
   └─▶ 2b. ingest_ipca_monthly  (mesma lógica + check de mês)
           │
           ├─▶ SELECT MAX(date) FROM bronze_bcb.ipca_monthly
           │     • Mês corrente já gravado → AirflowSkipException
           │     • Vazio ou mês anterior   → fetch + upsert
           │
           └─▶ bcb.sgs.get({IPCA: 433}, start, end) → upsert
```

---

## Integration Points

| Sistema Externo         | Tipo de Integração           | Autenticação          | Notas                                          |
|-------------------------|------------------------------|-----------------------|------------------------------------------------|
| BCB SGS API             | REST via `python-bcb` (sgs)  | Pública, sem auth     | Rate limiting não documentado; retry=2 no Airflow |
| PostgreSQL 15 (finlake) | `PostgresHook` (psycopg2)    | Via `AIRFLOW_CONN_*`  | Host `postgres:5432` na rede Docker           |

---

## Testing Strategy

| Tipo        | Escopo                                | Arquivo                              | Ferramenta           | Cobertura           |
|-------------|---------------------------------------|--------------------------------------|----------------------|---------------------|
| Unit        | `get_load_range()` — 5 cenários       | `tests/domain_bcb/test_bcb_client.py`| pytest + unittest.mock | Todos os branches |
| Unit        | `_upsert_dataframe()` — 3 cenários    | `tests/domain_bcb/test_loaders.py`   | pytest + MagicMock   | Caminho feliz + vazio |
| Unit        | `fetch_series()` — mock sgs.get       | `tests/domain_bcb/test_bcb_client.py`| pytest + patch       | Retorno normal + vazio |
| Smoke (manual) | DAG parse sem erros             | Airflow UI / `airflow dags list`     | Airflow CLI          | AT-001 pre-check    |
| Smoke (manual) | Primeira execução da DAG        | Airflow UI                           | —                    | AT-001, AT-006, AT-007 |

### Cenários de Unit Test para `get_load_range()`

| Cenário                            | Setup do mock                             | Expected                              |
|------------------------------------|-------------------------------------------|---------------------------------------|
| Tabela vazia (backfill)            | `get_first` retorna `(None,)`             | `(start_date_config, today)`          |
| Tabela com dados antigos (delta)   | `get_first` retorna `(date(2026,4,20),)`  | `(date(2026,4,21), today)`            |
| Tabela atualizada para hoje        | `get_first` retorna `(today,)`            | `None`                                |
| IPCA — mês corrente já gravado     | `get_first` retorna `(today.replace(day=1),)` | `None`                            |
| IPCA — mês anterior ainda pendente | `get_first` retorna `(date(2026,3,1),)`   | `(date(2026,3,2), today)`             |

---

## Error Handling

| Tipo de Erro                           | Estratégia                                              | Retry? |
|----------------------------------------|---------------------------------------------------------|--------|
| API BCB indisponível / timeout         | Exceção propaga → Airflow retry (2x, intervalo 5min)    | Sim    |
| DataFrame vazio da API                 | Log warning + `AirflowSkipException`                    | Não    |
| `AIRFLOW_CONN_FINLAKE_POSTGRES` ausente | `AirflowNotFoundException` no hook → task falha         | Não    |
| PostgreSQL indisponível                | Exceção psycopg2 → Airflow retry                        | Sim    |
| Erro de tipo / conversão no DataFrame  | `ValueError` / `KeyError` → task falha sem retry        | Não    |
| `rollback()` em falha de INSERT        | Explícito no `_upsert_dataframe()` via try/finally      | N/A    |

---

## Configuration

| Parâmetro                          | Tipo    | Valor                                    | Onde configurar             |
|------------------------------------|---------|------------------------------------------|-----------------------------|
| `AIRFLOW_CONN_FINLAKE_POSTGRES`    | string  | `postgresql://user:pass@postgres:5432/db`| `.env` → `compose.airflow.yml` |
| `start_date` SELIC                 | date    | `2000-01-01`                             | `SERIES_CONFIG` em `bcb_client.py` |
| `start_date` IPCA                  | date    | `1994-07-01`                             | `SERIES_CONFIG` em `bcb_client.py` |
| `start_date` PTAX                  | date    | `1999-01-01`                             | `SERIES_CONFIG` em `bcb_client.py` |
| `retries`                          | int     | `2`                                      | `_DEFAULT_ARGS` em `dag_bronze_bcb.py` |
| `retry_delay`                      | timedelta | `5 minutos`                            | `_DEFAULT_ARGS` em `dag_bronze_bcb.py` |
| `schedule`                         | string  | `@daily`                                 | `@dag` decorator             |

---

## Security Considerations

- Zero credenciais hardcoded: `POSTGRES_PASSWORD` sempre via `.env` (git-ignored).
- `AIRFLOW_CONN_FINLAKE_POSTGRES` injetada via variável de ambiente no container,
  não commitada no `compose.airflow.yml` (referência `${VAR}`).
- API BCB é pública e sem autenticação — sem secrets a gerenciar no lado do cliente.
- PostgreSQL acessível apenas na rede Docker interna (`finlake-net`); porta 5433
  no host é para acesso de desenvolvimento, não exposta externamente.

---

## Observability

| Aspecto     | Implementação                                                                          |
|-------------|----------------------------------------------------------------------------------------|
| Logging     | `logging.getLogger(__name__)` em cada módulo — logs aparecem no Airflow Task Logs UI  |
| Métricas    | Airflow UI: duração de task, status (Success / Skipped / Failed) por run               |
| Rastreabilidade | `ingested_at` e `source_api` em todas as tabelas Bronze para auditoria de dados   |
| Alertas     | `retries=2` + Airflow UI para falhas; alertas por e-mail deferidos (YAGNI)             |

---

## Pipeline Architecture

### DAG Diagram

```text
                       dag_bronze_bcb (@daily)
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
   ingest_selic_daily  ingest_ipca_monthly  ingest_ptax_daily
   (Success ou Skip)   (Success ou Skip)    (Success ou Skip)
```

### Partition Strategy

| Tabela                   | Partition Key | Granularidade | Rationale                                        |
|--------------------------|---------------|---------------|--------------------------------------------------|
| `bronze_bcb.selic_daily` | `date` (PK)   | Diária        | Volume baixo (~6.500 registros); sem partição física necessária |
| `bronze_bcb.ipca_monthly`| `date` (PK)   | Mensal        | Volume muito baixo (~390 registros); sem partição física necessária |
| `bronze_bcb.ptax_daily`  | `date` (PK)   | Diária        | Volume baixo (~6.500 registros); sem partição física necessária |

> Particionamento físico (PostgreSQL PARTITION BY RANGE) é candidato a evolução
> quando o volume acumular >10 anos de dados. Não necessário no MVP.

### Incremental Strategy

| Série    | Estratégia          | Coluna-chave | Lookback               |
|----------|---------------------|--------------|------------------------|
| SELIC    | `MAX(date)` + delta | `date`       | +1 dia a partir do MAX |
| IPCA     | `MAX(date)` + delta | `date`       | Verifica mês corrente  |
| PTAX     | `MAX(date)` + delta | `date`       | +1 dia a partir do MAX |

### Schema Evolution Plan

| Tipo de mudança                  | Estratégia                                        | Rollback               |
|----------------------------------|---------------------------------------------------|------------------------|
| Nova coluna nullable             | `ALTER TABLE ... ADD COLUMN ... DEFAULT NULL`     | `DROP COLUMN`          |
| Nova coluna NOT NULL             | Add nullable → backfill → set NOT NULL            | `DROP COLUMN`          |
| Mudança de tipo NUMERIC          | Dual-write em nova coluna + migração              | Reverter tipo          |
| Nova série BCB                  | Nova entrada em `SERIES_CONFIG` + nova tabela     | Remover entrada + tabela |

### Data Quality Gates (Bronze)

| Gate                         | Verificação                          | Threshold     | Ação em falha                    |
|------------------------------|--------------------------------------|---------------|----------------------------------|
| Null em `valor`              | `WHERE valor IS NULL`                | 0 nulls       | Log warning + não inserir linha  |
| Contagem mínima pós-backfill | `COUNT(*) >= threshold` por série    | Ver abaixo    | Investigar manualmente           |
| `date` em dias úteis (SELIC) | Verificação downstream na Silver     | N/A Bronze    | Concern da Silver layer          |

**Thresholds de contagem após backfill completo:**
- `selic_daily`: ≥ 6.000 registros
- `ipca_monthly`: ≥ 380 registros
- `ptax_daily`: ≥ 6.000 registros

---

## Revision History

| Versão | Data       | Autor        | Mudanças                                    |
|--------|------------|--------------|---------------------------------------------|
| 1.0    | 2026-04-23 | design-agent | Versão inicial from DEFINE_BRONZE_BCB.md    |

---

## Next Step

**Pronto para:** `/build .claude/sdd/features/DESIGN_BRONZE_BCB.md`
