# DESIGN: Bronze CVM — Ingestão de Fundos de Investimento

> Arquitetura técnica para ingestão do cadastro de fundos (`cad_fi.csv`) e
> informe diário (`inf_diario_fi_YYYYMM.zip`) da CVM no schema `bronze_cvm`
> do PostgreSQL 15, com carga histórica via PySpark e delta incremental via Airflow.

## Metadata

| Atributo          | Valor                                              |
|-------------------|----------------------------------------------------|
| **Feature**       | BRONZE_CVM                                         |
| **Data**          | 2026-04-27                                         |
| **Autor**         | Nilton Coura                                       |
| **Status**        | ✅ Shipped                                 |
| **Origem**        | DEFINE_BRONZE_CVM.md                               |

---

## Arquitetura

```
CVM Portal (dados.cvm.gov.br)
│
├── cad_fi.csv ──────────────────────────────────────────────────────────┐
│   latin1 · separador ; · ~30k fundos · atualizado diariamente         │
│                                                                         │
│                    ┌────────────────────────────────────────────────┐  │
│                    │ dag_bronze_cvm_cadastro (@daily)                │  │
│                    │  └── ingest_cadastro()                         │  │
│                    │       └── cvm_client                            │  │
│                    │           ├── download_bytes()                  │  │
│                    │           ├── parse_csv_bytes()                 │  │
│                    │           ├── validate_cadastro_rows()          │  │
│                    │           └── upsert SCD Tipo 1                 │◄─┘
│                    └──────────────────┬─────────────────────────────┘
│                                       │
│                                       ▼
│                            bronze_cvm.cadastro
│                            (SCD Tipo 1 · ~30k rows · 40 colunas)
│
└── inf_diario_fi_YYYYMM.zip ─────────────────────────────────────────┐
    │                                                                   │
    ├── BULK histórico (PySpark)       ├── DELTA mensal (Airflow)      │
    │   scripts/spark/                 │   dag_bronze_cvm_informe      │
    │   historical_load_cvm.py         │   (@monthly · catchup=False)  │
    │   --start-year X --end-year Y    │    └── ingest_informe_mensal()|
    │                                  │         └── cvm_client        │
    │   ≤2020: HIST/YYYY.zip (anual)   │             ├── build_informe_url()
    │   2021+: DADOS/YYYYMM.zip (mês)  │             ├── download_bytes()
    │                                  │             ├── unzip_csv()   │
    │   SparkSession local[*]          │             ├── parse_csv_bytes()
    │   DataFrame → JDBC append        │             ├── validate_informe_rows()
    │                                  │             └── ON CONFLICT DO NOTHING
    └──────────────────────────────────┘
                      │
                      ▼
         bronze_cvm.informe_diario
         PARTITION BY RANGE (dt_comptc)
         ├── informe_diario_hist  (2000-01-01 → 2021-01-01)
         ├── informe_diario_2021  (2021 → 2022)
         ├── informe_diario_2022  (2022 → 2023)
         ├── informe_diario_2023  (2023 → 2024)
         ├── informe_diario_2024  (2024 → 2025)
         ├── informe_diario_2025  (2025 → 2026)
         └── informe_diario_2026  (2026 → 2027)
```

---

## Componentes

| Componente                               | Responsabilidade                                                      |
|------------------------------------------|-----------------------------------------------------------------------|
| `004_bronze_cvm.sql`                     | DDL: schema, tabelas (40 colunas cadastro), partições por ano         |
| `cvm_client.py`                          | I/O: URL builder, download HTTP, unzip BytesIO, parse latin1, Pydantic|
| `loaders_cadastro.py`                    | Airflow callable: busca cadastro, valida, upsert SCD Tipo 1           |
| `loaders_informe.py`                     | Airflow callable: determina mês anterior, busca ZIP, valida, insere   |
| `dag_bronze_cvm_cadastro.py`             | DAG `@daily`, 1 task                                                  |
| `dag_bronze_cvm_informe.py`              | DAG `@monthly`, `catchup=False`, 1 task                               |
| `historical_load_cvm.py`                 | PySpark standalone: bulk histórico com `--start-year`/`--end-year`    |
| `test_cvm_client.py`                     | Unit tests: URL builder, unzip, parse, Pydantic                       |
| `test_loaders_cadastro.py`               | Unit tests: upsert SCD Tipo 1, mocks PostgresHook                     |
| `test_loaders_informe.py`                | Unit tests: detecção mês anterior, insert idempotente                 |

---

## Decisões de Arquitetura (ADRs)

### ADR-01: `cvm_client.py` centraliza todo I/O — separação de concerns

| Atributo    | Valor      |
|-------------|------------|
| **Status**  | Accepted   |
| **Data**    | 2026-04-27 |

**Context:** O BCB usa o mesmo padrão: `bcb_client.py` concentra toda a
lógica de acesso à API. O CVM tem formatos distintos (CSV direto e ZIP com
CSV interno), dois schemas de URL (HIST/ e DADOS/), e encoding não-padrão (latin1).

**Choice:** `cvm_client.py` concentra: `build_informe_url()`, `download_bytes()`,
`unzip_csv()`, `parse_csv_bytes()`, `validate_cadastro_rows()`,
`validate_informe_rows()`, modelos Pydantic, e helpers `_safe_float`/`_safe_int`.

**Rationale:** Loaders Airflow e script PySpark importam as mesmas funções —
sem duplicação de lógica de I/O. Testes unitários cobrem apenas `cvm_client.py`
sem mockar Airflow ou Spark.

**Alternatives Rejected:**
1. Lógica de download inline nos loaders — duplicação entre `loaders_informe.py` e o script PySpark.
2. Módulos separados `cvm_downloader.py` + `cvm_parser.py` — granularidade excessiva para este escopo.

**Consequences:**
- PySpark script importa `cvm_client.py` diretamente sem dependência de Airflow.
- Mudança no formato CVM tem um único ponto de correção.

---

### ADR-02: Pydantic valida apenas campos críticos — não toda a linha

| Atributo    | Valor      |
|-------------|------------|
| **Status**  | Accepted   |
| **Data**    | 2026-04-27 |

**Context:** O cadastro tem 40 colunas. Validar todos os tipos e constraints
aumenta o acoplamento com a fonte — a CVM já alterou o schema em versões anteriores.

**Choice:** Validação Pydantic obrigatória apenas para:
- `CNPJ_FUNDO` em ambas as tabelas: não pode ser vazio (é a PK).
- `DT_COMPTC` no informe: deve ser uma data válida.
- Campos numéricos do informe aceitam `None` — sem erro se ausentes.
Linhas com `CNPJ_FUNDO` inválido são descartadas com `logger.warning`.

**Rationale:** Bronze é camada de ingestão bruta. O único invariante absoluto
é que a PK não pode ser vazia — sem isso o `ON CONFLICT` falha silenciosamente.

**Alternatives Rejected:**
1. Validação completa de todos os campos — frágil contra mudanças de schema.
2. Sem validação — CNPJ vazio causaria erro de PK críptico no PostgreSQL.

---

### ADR-03: PySpark usa JDBC `append` — sem coordenação com Airflow

| Atributo    | Valor      |
|-------------|------------|
| **Status**  | Accepted   |
| **Data**    | 2026-04-27 |

**Context:** Dois sistemas (PySpark e Airflow) escrevem na mesma tabela.
A PK composta `(cnpj_fundo, dt_comptc)` com `ON CONFLICT DO NOTHING`
garante que rodar ambos sobre o mesmo período não duplica dados.

**Choice:** PySpark usa `df.write.jdbc(mode="append")`. Idempotência é
responsabilidade exclusiva da constraint de PK no banco — não do sistema de escrita.

**Rationale:** A PK é a fonte de verdade. Qualquer sistema de escrita tem a
mesma garantia sem coordenação explícita.

**Alternatives Rejected:**
1. `mode="overwrite"` no PySpark — apagaria partições completas.
2. DELETE + INSERT por mês — cria janela de dados ausentes em caso de falha.

**Consequences:**
- Script PySpark pode ser re-executado qualquer número de vezes com segurança.
- Em caso de crash, registros já inseridos são mantidos — basta re-executar.

---

### ADR-04: `@monthly` com `catchup=False` — Airflow processa apenas delta

| Atributo    | Valor      |
|-------------|------------|
| **Status**  | Accepted   |
| **Data**    | 2026-04-27 |

**Context:** O PySpark cuida de todo o histórico. O DAG Airflow existe apenas
para capturar os meses novos após o deploy. Com `catchup=True`, o Airflow
tentaria processar todos os meses desde `start_date`, redundante e lento.

**Choice:** `catchup=False`, `start_date=datetime(2024, 1, 1)`. O DAG processa
sempre o mês imediatamente anterior ao mês corrente (`today.replace(day=1) - timedelta(days=1)`).

**Rationale:** Separação clara: PySpark = histórico, Airflow = delta.
`ON CONFLICT DO NOTHING` garante segurança se os dois cobrirem o mesmo mês.

---

## File Manifest

| # | Arquivo                                             | Ação      | Propósito                                          | Deps |
|---|-----------------------------------------------------|-----------|----------------------------------------------------|------|
| 1 | `docker/postgres/migrations/004_bronze_cvm.sql`    | Create    | Schema + 40 colunas cadastro + partições informe   | —    |
| 2 | `dags/domain_cvm/__init__.py`                      | Create    | Package Python do domínio CVM                      | —    |
| 3 | `dags/domain_cvm/ingestion/__init__.py`            | Create    | Package do módulo de ingestão                      | 2    |
| 4 | `dags/domain_cvm/ingestion/cvm_client.py`          | Create    | I/O: download, unzip, parse, Pydantic, helpers     | 3    |
| 5 | `dags/domain_cvm/ingestion/loaders_cadastro.py`    | Create    | Callable Airflow: ingest_cadastro (SCD Tipo 1)     | 4    |
| 6 | `dags/domain_cvm/ingestion/loaders_informe.py`     | Create    | Callable Airflow: ingest_informe_mensal            | 4    |
| 7 | `dags/domain_cvm/dag_bronze_cvm_cadastro.py`       | Create    | DAG @daily — cadastro de fundos                    | 5    |
| 8 | `dags/domain_cvm/dag_bronze_cvm_informe.py`        | Create    | DAG @monthly — informe diário (delta mensal)       | 6    |
| 9 | `scripts/spark/historical_load_cvm.py`             | Create    | PySpark bulk histórico — importa cvm_client        | 4    |
| 10| `tests/domain_cvm/__init__.py`                     | Create    | Package de testes do domínio CVM                   | —    |
| 11| `tests/domain_cvm/test_cvm_client.py`              | Create    | Unit tests: URL, unzip, parse, Pydantic, helpers   | 4    |
| 12| `tests/domain_cvm/test_loaders_cadastro.py`        | Create    | Unit tests: upsert SCD Tipo 1 com mock hook        | 5    |
| 13| `tests/domain_cvm/test_loaders_informe.py`         | Create    | Unit tests: mês anterior, insert idempotente       | 6    |
| 14| `Makefile`                                         | Modify    | Adicionar 004 ao migrate; novo target cvm-hist-load| 1, 9 |

---

## Code Patterns

### 1. `004_bronze_cvm.sql` — DDL completo (todas as 40 colunas do cadastro)

```sql
-- Domínio CVM — schema e tabelas Bronze
-- Execute: psql -U postgres -d finlake -f docker/postgres/migrations/004_bronze_cvm.sql
-- Idempotente: IF NOT EXISTS em todas as operações

CREATE SCHEMA IF NOT EXISTS bronze_cvm;

COMMENT ON SCHEMA bronze_cvm IS
    'Bronze layer — domínio CVM (Comissão de Valores Mobiliários). '
    'Dados brutos sem transformação. Espelho do estado atual da fonte.';

-- ---------------------------------------------------------------------------
-- CADASTRO DE FUNDOS — cad_fi.csv (SCD Tipo 1)
-- 40 colunas da fonte + 3 colunas de auditoria
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_cvm.cadastro (
    -- Identificação principal
    cnpj_fundo           VARCHAR(18)   NOT NULL,
    tp_fundo             VARCHAR(100),
    denom_social         VARCHAR(200),
    cd_cvm               VARCHAR(20),

    -- Ciclo de vida do fundo
    dt_reg               DATE,
    dt_const             DATE,
    dt_cancel            DATE,
    dt_ini_ativ          DATE,
    dt_fim_ativ          DATE,
    dt_ini_sit           DATE,
    dt_ini_exerc         DATE,
    dt_fim_exerc         DATE,

    -- Situação, classificação e público
    sit                  VARCHAR(80),
    classe               VARCHAR(100),
    classe_anbima        VARCHAR(100),
    rentab_fundo         VARCHAR(200),
    publico_alvo         VARCHAR(200),

    -- Estrutura e características
    condom               VARCHAR(20),
    fundo_cotas          VARCHAR(1),
    fundo_exclusivo      VARCHAR(1),
    trib_lprazo          VARCHAR(1),
    entid_invest         VARCHAR(1),
    invest_cempr_exter   VARCHAR(1),

    -- Taxas e informações complementares
    taxa_perfm           NUMERIC(10,4),
    inf_taxa_perfm       VARCHAR(300),
    taxa_adm             NUMERIC(10,4),
    inf_taxa_adm         VARCHAR(300),

    -- Patrimônio líquido
    vl_patrim_liq        NUMERIC(18,6),
    dt_patrim_liq        DATE,

    -- Administrador
    cnpj_admin           VARCHAR(18),
    admin                VARCHAR(200),
    diretor              VARCHAR(200),

    -- Gestor
    pf_pj_gestor         VARCHAR(2),
    cpf_cnpj_gestor      VARCHAR(18),
    gestor               VARCHAR(200),

    -- Auditor
    cnpj_auditor         VARCHAR(18),
    auditor              VARCHAR(200),

    -- Custodiante
    cnpj_custodiante     VARCHAR(18),
    custodiante          VARCHAR(200),

    -- Controlador
    cnpj_controlador     VARCHAR(18),
    controlador          VARCHAR(200),

    -- Auditoria (geradas na ingestão — não presentes no CSV)
    ingested_at          TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP     NOT NULL DEFAULT NOW(),
    source_url           VARCHAR(300)  NOT NULL,

    CONSTRAINT cadastro_pkey PRIMARY KEY (cnpj_fundo)
);

COMMENT ON TABLE  bronze_cvm.cadastro              IS 'Cadastro de fundos — cad_fi.csv. SCD Tipo 1.';
COMMENT ON COLUMN bronze_cvm.cadastro.cnpj_fundo   IS 'CNPJ do fundo (PK). Formato: XX.XXX.XXX/XXXX-XX';
COMMENT ON COLUMN bronze_cvm.cadastro.updated_at   IS 'Timestamp da última atualização via ON CONFLICT DO UPDATE';
COMMENT ON COLUMN bronze_cvm.cadastro.source_url   IS 'URL do arquivo de origem (CADASTRO_URL)';

-- ---------------------------------------------------------------------------
-- INFORME DIÁRIO — inf_diario_fi_YYYYMM.zip (particionado por ano)
-- 9 colunas da fonte + 2 colunas de auditoria
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario (
    tp_fundo        VARCHAR(10),
    cnpj_fundo      VARCHAR(18)    NOT NULL,
    dt_comptc       DATE           NOT NULL,
    vl_total        NUMERIC(18,6),
    vl_quota        NUMERIC(18,8),
    vl_patrim_liq   NUMERIC(18,6),
    captc_dia       NUMERIC(18,6),
    resg_dia        NUMERIC(18,6),
    nr_cotst        INTEGER,
    ingested_at     TIMESTAMP      NOT NULL DEFAULT NOW(),
    source_url      VARCHAR(300)   NOT NULL,
    CONSTRAINT informe_diario_pkey PRIMARY KEY (cnpj_fundo, dt_comptc)
) PARTITION BY RANGE (dt_comptc);

COMMENT ON TABLE  bronze_cvm.informe_diario           IS 'Informe diário de fundos — inf_diario_fi_YYYYMM.zip. Particionado por ano.';
COMMENT ON COLUMN bronze_cvm.informe_diario.dt_comptc IS 'Data de competência (chave de partição + PK)';
COMMENT ON COLUMN bronze_cvm.informe_diario.cnpj_fundo IS 'FK lógica para bronze_cvm.cadastro';

-- Bloco histórico imutável 2000–2020 (arquivos anuais HIST/)
CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_hist
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2000-01-01') TO ('2021-01-01');

-- Partições anuais para dados incrementais (2021+)
CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2021
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2022
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2022-01-01') TO ('2023-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2023
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2023-01-01') TO ('2024-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2024
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2025
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2025-01-01') TO ('2026-01-01');

CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_2026
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
```

---

### 2. `cvm_client.py` — I/O centralizado

```python
"""Módulo de acesso ao portal de dados abertos da CVM.

Responsabilidades:
- build_informe_url: bifurcação HIST/ (≤2020) vs DADOS/ (2021+).
- download_bytes: HTTP GET com timeout configurável.
- unzip_csv: descompressão em memória via BytesIO.
- parse_csv_bytes: parse CSV latin1 em DataFrame.
- validate_cadastro_rows / validate_informe_rows: Pydantic para campos críticos.
- _safe_float / _safe_int: conversão tolerante para valores numéricos CVM.
"""
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date
from typing import Optional

import pandas as pd
import requests
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

CVM_BASE = "https://dados.cvm.gov.br/dados/FI"
CADASTRO_URL = f"{CVM_BASE}/CAD/DADOS/cad_fi.csv"
_INFORME_BASE = f"{CVM_BASE}/DOC/INF_DIARIO/DADOS"


def build_informe_url(year: int, month: int) -> str:
    """Retorna URL do ZIP do informe diário.

    Para anos ≤ 2020, retorna arquivo anual (HIST/).
    Para 2021+, retorna arquivo mensal (DADOS/).
    O parâmetro month é ignorado para anos ≤ 2020.
    """
    if year <= 2020:
        return f"{_INFORME_BASE}/HIST/inf_diario_fi_{year}.zip"
    return f"{_INFORME_BASE}/inf_diario_fi_{year}{month:02d}.zip"


def download_bytes(url: str, timeout: int = 120) -> bytes:
    """Faz download de um arquivo via HTTP GET e retorna os bytes brutos."""
    logger.info("Download: %s", url)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.content


def unzip_csv(zip_bytes: bytes) -> bytes:
    """Descomprime o primeiro .csv encontrado dentro de um ZIP em memória."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        logger.info("Descomprimindo: %s", csv_name)
        return zf.read(csv_name)


def parse_csv_bytes(
    content: bytes,
    sep: str = ";",
    encoding: str = "latin1",
) -> pd.DataFrame:
    """Faz parse de bytes CSV em DataFrame, preservando todos os campos como str."""
    return pd.read_csv(
        io.BytesIO(content),
        sep=sep,
        encoding=encoding,
        dtype=str,
        low_memory=False,
    )


# ---------------------------------------------------------------------------
# Modelos Pydantic — validação dos campos críticos (PK e chave de partição)
# ---------------------------------------------------------------------------

class InformeRecord(BaseModel):
    """Validação mínima de uma linha do informe diário."""

    tp_fundo: Optional[str] = None
    cnpj_fundo: str
    dt_comptc: date
    vl_total: Optional[float] = None
    vl_quota: Optional[float] = None
    vl_patrim_liq: Optional[float] = None
    captc_dia: Optional[float] = None
    resg_dia: Optional[float] = None
    nr_cotst: Optional[int] = None

    @field_validator("cnpj_fundo")
    @classmethod
    def cnpj_nao_vazio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("CNPJ_FUNDO não pode ser vazio")
        return v.strip()


class CadastroRecord(BaseModel):
    """Validação mínima de uma linha do cadastro — apenas CNPJ_FUNDO (PK)."""

    cnpj_fundo: str

    @field_validator("cnpj_fundo")
    @classmethod
    def cnpj_nao_vazio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("CNPJ_FUNDO não pode ser vazio")
        return v.strip()


# ---------------------------------------------------------------------------
# Funções de validação em batch — descartar linhas inválidas com warning
# ---------------------------------------------------------------------------

def validate_cadastro_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Descarta linhas com CNPJ_FUNDO inválido. Preserva as demais."""
    mask = df["CNPJ_FUNDO"].notna() & df["CNPJ_FUNDO"].str.strip().astype(bool)
    discarded = int((~mask).sum())
    if discarded:
        logger.warning("%d linhas de cadastro descartadas (CNPJ_FUNDO vazio).", discarded)
    return df[mask].copy()


def validate_informe_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Valida campos críticos do informe linha a linha. Descarta inválidos."""
    valid_rows: list[dict] = []
    discarded = 0

    for _, row in df.iterrows():
        try:
            InformeRecord(
                tp_fundo=row.get("TP_FUNDO") or None,
                cnpj_fundo=str(row.get("CNPJ_FUNDO", "")),
                dt_comptc=pd.to_datetime(row["DT_COMPTC"]).date(),
                vl_total=_safe_float(row.get("VL_TOTAL")),
                vl_quota=_safe_float(row.get("VL_QUOTA")),
                vl_patrim_liq=_safe_float(row.get("VL_PATRIM_LIQ")),
                captc_dia=_safe_float(row.get("CAPTC_DIA")),
                resg_dia=_safe_float(row.get("RESG_DIA")),
                nr_cotst=_safe_int(row.get("NR_COTST")),
            )
            valid_rows.append(row.to_dict())
        except Exception as exc:
            logger.warning(
                "Linha descartada — CNPJ: %s | erro: %s",
                row.get("CNPJ_FUNDO"),
                exc,
            )
            discarded += 1

    if discarded:
        logger.warning("%d linhas do informe descartadas na validação.", discarded)
    return pd.DataFrame(valid_rows) if valid_rows else pd.DataFrame(columns=df.columns)


# ---------------------------------------------------------------------------
# Helpers de conversão tolerante
# ---------------------------------------------------------------------------

def _safe_float(val: object) -> Optional[float]:
    """Converte string/número para float. Retorna None em caso de falha."""
    try:
        s = str(val).replace(",", ".").strip()
        return float(s) if s and s.lower() != "nan" else None
    except (ValueError, TypeError):
        return None


def _safe_int(val: object) -> Optional[int]:
    """Converte string/número para int. Retorna None em caso de falha."""
    try:
        s = str(val).strip()
        return int(float(s)) if s and s.lower() != "nan" else None
    except (ValueError, TypeError):
        return None
```

---

### 3. `loaders_cadastro.py` — SCD Tipo 1

```python
"""Callable Airflow: ingestão diária do cadastro de fundos CVM.

SCD Tipo 1: ON CONFLICT (cnpj_fundo) DO UPDATE — espelha estado atual.
"""
from __future__ import annotations

import logging

import pandas as pd
from airflow.providers.postgres.hooks.postgres import PostgresHook

from domain_cvm.ingestion.cvm_client import (
    CADASTRO_URL,
    download_bytes,
    parse_csv_bytes,
    validate_cadastro_rows,
)

logger = logging.getLogger(__name__)

CONN_ID = "finlake_postgres"

# Mapeamento CSV → coluna PostgreSQL (todas as 40 colunas)
_CSV_TO_DB: dict[str, str] = {
    "CNPJ_FUNDO": "cnpj_fundo", "TP_FUNDO": "tp_fundo",
    "DENOM_SOCIAL": "denom_social", "CD_CVM": "cd_cvm",
    "DT_REG": "dt_reg", "DT_CONST": "dt_const", "DT_CANCEL": "dt_cancel",
    "DT_INI_ATIV": "dt_ini_ativ", "DT_FIM_ATIV": "dt_fim_ativ",
    "SIT": "sit", "DT_INI_SIT": "dt_ini_sit",
    "DT_INI_EXERC": "dt_ini_exerc", "DT_FIM_EXERC": "dt_fim_exerc",
    "CLASSE": "classe", "CLASSE_ANBIMA": "classe_anbima",
    "RENTAB_FUNDO": "rentab_fundo", "PUBLICO_ALVO": "publico_alvo",
    "CONDOM": "condom", "FUNDO_COTAS": "fundo_cotas",
    "FUNDO_EXCLUSIVO": "fundo_exclusivo", "TRIB_LPRAZO": "trib_lprazo",
    "ENTID_INVEST": "entid_invest", "INVEST_CEMPR_EXTER": "invest_cempr_exter",
    "TAXA_PERFM": "taxa_perfm", "INF_TAXA_PERFM": "inf_taxa_perfm",
    "TAXA_ADM": "taxa_adm", "INF_TAXA_ADM": "inf_taxa_adm",
    "VL_PATRIM_LIQ": "vl_patrim_liq", "DT_PATRIM_LIQ": "dt_patrim_liq",
    "CNPJ_ADMIN": "cnpj_admin", "ADMIN": "admin", "DIRETOR": "diretor",
    "PF_PJ_GESTOR": "pf_pj_gestor", "CPF_CNPJ_GESTOR": "cpf_cnpj_gestor",
    "GESTOR": "gestor", "CNPJ_AUDITOR": "cnpj_auditor", "AUDITOR": "auditor",
    "CNPJ_CUSTODIANTE": "cnpj_custodiante", "CUSTODIANTE": "custodiante",
    "CNPJ_CONTROLADOR": "cnpj_controlador", "CONTROLADOR": "controlador",
}


def ingest_cadastro(**kwargs: object) -> None:
    """Task Airflow: ingestão diária do cadastro de fundos CVM (SCD Tipo 1).

    Baixa cad_fi.csv (latin1), valida CNPJ_FUNDO, faz upsert de todas as
    colunas mapeadas. Campos ausentes no CSV são ignorados.
    """
    content = download_bytes(CADASTRO_URL)
    df = parse_csv_bytes(content)
    df = validate_cadastro_rows(df)

    # Rename CSV columns → DB columns; filtrar apenas as presentes no CSV
    df = df.rename(columns=_CSV_TO_DB)
    db_cols = [c for c in _CSV_TO_DB.values() if c in df.columns]
    df = df[db_cols].copy()

    # Substituir NaN por None para evitar inserção de strings "nan"
    df = df.where(pd.notna(df), other=None)

    hook = PostgresHook(postgres_conn_id=CONN_ID)
    _upsert_cadastro(hook, df)


def _upsert_cadastro(hook: PostgresHook, df: pd.DataFrame) -> None:
    """Executa upsert SCD Tipo 1 para o cadastro."""
    cols = list(df.columns)
    placeholders = ", ".join(["%s"] * len(cols))
    update_cols = [c for c in cols if c != "cnpj_fundo"]
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    sql = f"""
        INSERT INTO bronze_cvm.cadastro ({", ".join(cols)}, source_url, updated_at)
        VALUES ({placeholders}, %s, NOW())
        ON CONFLICT (cnpj_fundo) DO UPDATE SET
            {updates},
            source_url = EXCLUDED.source_url,
            updated_at = NOW()
    """

    rows = [(*row, CADASTRO_URL) for row in df.itertuples(index=False, name=None)]

    conn = hook.get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "cadastro: %d registros processados (ON CONFLICT DO UPDATE).", len(rows)
    )
```

---

### 4. `loaders_informe.py` — delta mensal

```python
"""Callable Airflow: ingestão mensal do informe diário CVM.

Processa sempre o mês anterior ao mês corrente.
Idempotência via ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
from airflow.providers.postgres.hooks.postgres import PostgresHook

from domain_cvm.ingestion.cvm_client import (
    _safe_float,
    _safe_int,
    build_informe_url,
    download_bytes,
    parse_csv_bytes,
    unzip_csv,
    validate_informe_rows,
)

logger = logging.getLogger(__name__)

CONN_ID = "finlake_postgres"

_INSERT_SQL = """
    INSERT INTO bronze_cvm.informe_diario
        (tp_fundo, cnpj_fundo, dt_comptc, vl_total, vl_quota,
         vl_patrim_liq, captc_dia, resg_dia, nr_cotst, source_url)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING
"""


def ingest_informe_mensal(**kwargs: object) -> None:
    """Task Airflow: ingestão do informe diário do mês anterior ao corrente.

    Frequência: @monthly, catchup=False.
    Determina automaticamente year/month para garantir disponibilidade na CVM.
    """
    today = date.today()
    last_month = today.replace(day=1) - timedelta(days=1)
    year, month = last_month.year, last_month.month

    url = build_informe_url(year, month)
    logger.info("Processando informe %d-%02d: %s", year, month, url)

    zip_bytes = download_bytes(url)
    csv_bytes = unzip_csv(zip_bytes)
    df = parse_csv_bytes(csv_bytes)
    df = validate_informe_rows(df)

    if df.empty:
        logger.warning("DataFrame vazio após validação — nenhum registro inserido.")
        return

    hook = PostgresHook(postgres_conn_id=CONN_ID)
    _insert_informe(hook, df, url)


def _insert_informe(hook: PostgresHook, df: pd.DataFrame, source_url: str) -> None:
    """Insere registros do informe com ON CONFLICT DO NOTHING."""
    rows = [
        (
            row.get("TP_FUNDO") or None,
            str(row["CNPJ_FUNDO"]).strip(),
            pd.to_datetime(row["DT_COMPTC"]).date(),
            _safe_float(row.get("VL_TOTAL")),
            _safe_float(row.get("VL_QUOTA")),
            _safe_float(row.get("VL_PATRIM_LIQ")),
            _safe_float(row.get("CAPTC_DIA")),
            _safe_float(row.get("RESG_DIA")),
            _safe_int(row.get("NR_COTST")),
            source_url,
        )
        for _, row in df.iterrows()
    ]

    conn = hook.get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(_INSERT_SQL, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    logger.info(
        "informe_diario: %d registros processados (ON CONFLICT DO NOTHING).", len(rows)
    )
```

---

### 5. `dag_bronze_cvm_cadastro.py`

```python
"""DAG de ingestão Bronze do domínio CVM — Cadastro de Fundos.

Ingestão diária do cad_fi.csv para bronze_cvm.cadastro. SCD Tipo 1.
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


@dag(
    dag_id="dag_bronze_cvm_cadastro",
    description="Bronze CVM: cadastro de fundos diário (cad_fi.csv → bronze_cvm.cadastro)",
    schedule="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["bronze", "cvm", "domain_funds", "medallion"],
)
def dag_bronze_cvm_cadastro() -> None:
    """DAG de ingestão do cadastro de fundos CVM."""

    PythonOperator(
        task_id="ingest_cadastro",
        python_callable=ingest_cadastro,
    )


dag_bronze_cvm_cadastro()
```

---

### 6. `dag_bronze_cvm_informe.py`

```python
"""DAG de ingestão Bronze do domínio CVM — Informe Diário (delta mensal).

Processa sempre o mês anterior. PySpark cuida do histórico.
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


@dag(
    dag_id="dag_bronze_cvm_informe",
    description="Bronze CVM: informe diário mensal (ZIP → bronze_cvm.informe_diario)",
    schedule="@monthly",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    default_args=_DEFAULT_ARGS,
    tags=["bronze", "cvm", "domain_funds", "medallion"],
)
def dag_bronze_cvm_informe() -> None:
    """DAG de ingestão do informe diário de fundos CVM."""

    PythonOperator(
        task_id="ingest_informe_mensal",
        python_callable=ingest_informe_mensal,
    )


dag_bronze_cvm_informe()
```

---

### 7. `historical_load_cvm.py` — PySpark bulk histórico

```python
"""Script PySpark para carga histórica do informe diário CVM.

Uso:
    spark-submit --jars postgresql-42.x.jar historical_load_cvm.py \\
        --start-year 2000 --end-year 2024

Variáveis de ambiente obrigatórias:
    FINLAKE_JDBC_URL      jdbc:postgresql://localhost:5433/finlake
    FINLAKE_JDBC_USER     postgres
    FINLAKE_JDBC_PASSWORD supabase123
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import date
from pathlib import Path

# Permite importar cvm_client mesmo fora do container Airflow
sys.path.insert(0, str(Path(__file__).parents[2] / "dags"))

import pandas as pd
from pyspark.sql import SparkSession
from pyspark.sql.types import (
    DateType, DoubleType, IntegerType, StringType, StructField, StructType,
)

from domain_cvm.ingestion.cvm_client import (
    _safe_float,
    _safe_int,
    build_informe_url,
    download_bytes,
    unzip_csv,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_TABLE = "bronze_cvm.informe_diario"

_SCHEMA = StructType([
    StructField("tp_fundo",      StringType(),  True),
    StructField("cnpj_fundo",    StringType(),  False),
    StructField("dt_comptc",     DateType(),    False),
    StructField("vl_total",      DoubleType(),  True),
    StructField("vl_quota",      DoubleType(),  True),
    StructField("vl_patrim_liq", DoubleType(),  True),
    StructField("captc_dia",     DoubleType(),  True),
    StructField("resg_dia",      DoubleType(),  True),
    StructField("nr_cotst",      IntegerType(), True),
    StructField("source_url",    StringType(),  False),
])


def _parse_to_pandas(csv_bytes: bytes, source_url: str) -> pd.DataFrame:
    """Converte bytes CSV para DataFrame no schema do informe_diario."""
    df = pd.read_csv(
        io.BytesIO(csv_bytes),
        sep=";",
        encoding="latin1",
        dtype=str,
        low_memory=False,
    )
    df = df[df["CNPJ_FUNDO"].notna() & df["CNPJ_FUNDO"].str.strip().astype(bool)]

    return pd.DataFrame({
        "tp_fundo":      df.get("TP_FUNDO"),
        "cnpj_fundo":    df["CNPJ_FUNDO"].str.strip(),
        "dt_comptc":     pd.to_datetime(df["DT_COMPTC"], errors="coerce").dt.date,
        "vl_total":      df.get("VL_TOTAL", pd.Series(dtype=str)).apply(_safe_float),
        "vl_quota":      df.get("VL_QUOTA", pd.Series(dtype=str)).apply(_safe_float),
        "vl_patrim_liq": df.get("VL_PATRIM_LIQ", pd.Series(dtype=str)).apply(_safe_float),
        "captc_dia":     df.get("CAPTC_DIA", pd.Series(dtype=str)).apply(_safe_float),
        "resg_dia":      df.get("RESG_DIA", pd.Series(dtype=str)).apply(_safe_float),
        "nr_cotst":      df.get("NR_COTST", pd.Series(dtype=str)).apply(_safe_int),
        "source_url":    source_url,
    }).dropna(subset=["cnpj_fundo", "dt_comptc"])


def _load_url(
    spark: SparkSession,
    url: str,
    jdbc_url: str,
    jdbc_props: dict,
) -> int:
    """Baixa, parseia e carrega um arquivo ZIP no PostgreSQL via JDBC."""
    try:
        zip_bytes = download_bytes(url)
        csv_bytes = unzip_csv(zip_bytes)
    except Exception as exc:
        logger.error("Falha no download/unzip %s: %s — pulando.", url, exc)
        return 0

    pdf = _parse_to_pandas(csv_bytes, url)
    if pdf.empty:
        logger.warning("DataFrame vazio para %s.", url)
        return 0

    sdf = spark.createDataFrame(pdf, schema=_SCHEMA)
    sdf.write.jdbc(url=jdbc_url, table=_TABLE, mode="append", properties=jdbc_props)
    logger.info("Carregado %s: %d registros.", url, pdf.shape[0])
    return int(pdf.shape[0])


def main() -> None:
    """Entry point: itera anos/meses e carrega cada arquivo via JDBC."""
    parser = argparse.ArgumentParser(description="Carga histórica CVM via PySpark")
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year",   type=int, required=True)
    args = parser.parse_args()

    jdbc_url = os.environ["FINLAKE_JDBC_URL"]
    jdbc_props = {
        "user":     os.environ["FINLAKE_JDBC_USER"],
        "password": os.environ["FINLAKE_JDBC_PASSWORD"],
        "driver":   "org.postgresql.Driver",
    }

    spark = (
        SparkSession.builder
        .master("local[*]")
        .appName("CVM_Historical_Load")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    today = date.today()
    total = 0

    for year in range(args.start_year, args.end_year + 1):
        if year <= 2020:
            # Arquivo anual — um único ZIP cobre o ano inteiro
            url = build_informe_url(year, 1)
            total += _load_url(spark, url, jdbc_url, jdbc_props)
        else:
            max_month = 12 if year < today.year else today.month - 1
            for month in range(1, max_month + 1):
                url = build_informe_url(year, month)
                total += _load_url(spark, url, jdbc_url, jdbc_props)

    logger.info("Carga histórica concluída. Total de registros processados: %d", total)
    spark.stop()


if __name__ == "__main__":
    main()
```

---

### 8. `Makefile` — modificação (targets novos)

```makefile
# Adicionar ao target migrate (após 003_gold_bcb):
    @echo "→ Executando migration 004_bronze_cvm (schema + tabelas + partições)..."
    @docker exec -i finlake-postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) \
        < docker/postgres/migrations/004_bronze_cvm.sql
    @echo "✓ Migration 004_bronze_cvm executada."

# Novo target (adicionar à lista .PHONY e ao corpo):
cvm-hist-load: ## Carga histórica CVM via PySpark (START_YEAR=XXXX END_YEAR=XXXX)
    @set -a && . ./.env && set +a && \
        spark-submit \
        --jars $(SPARK_JDBC_JAR) \
        scripts/spark/historical_load_cvm.py \
        --start-year $(START_YEAR) \
        --end-year $(END_YEAR)
```

---

### 9. `test_cvm_client.py` — padrão completo

```python
"""Unit tests para cvm_client.py.

Não requer Airflow nem PostgreSQL. Executável localmente com pytest.
"""
from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from domain_cvm.ingestion.cvm_client import (
    InformeRecord,
    _safe_float,
    _safe_int,
    build_informe_url,
    parse_csv_bytes,
    unzip_csv,
    validate_cadastro_rows,
    validate_informe_rows,
)


class TestBuildInformeUrl:
    def test_ano_2020_retorna_hist(self) -> None:
        assert "/HIST/inf_diario_fi_2020.zip" in build_informe_url(2020, 6)

    def test_ano_2000_retorna_hist(self) -> None:
        assert "/HIST/" in build_informe_url(2000, 1)

    def test_ano_2021_retorna_mensal(self) -> None:
        assert "inf_diario_fi_202103.zip" in build_informe_url(2021, 3)

    def test_mes_formatado_com_zero(self) -> None:
        assert "202501" in build_informe_url(2025, 1)

    def test_ano_2020_ignora_mes(self) -> None:
        url_jan = build_informe_url(2020, 1)
        url_jun = build_informe_url(2020, 6)
        assert url_jan == url_jun  # arquivo anual — mês não muda URL


class TestUnzipCsv:
    def _make_zip(self, filename: str, content: bytes) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(filename, content)
        return buf.getvalue()

    def test_descomprime_csv_corretamente(self) -> None:
        csv_content = b"CNPJ_FUNDO;DT_COMPTC\n12345;2024-01-01"
        result = unzip_csv(self._make_zip("informe.csv", csv_content))
        assert result == csv_content

    def test_case_insensitive_extensao(self) -> None:
        csv_content = b"COL;VAL\n1;2"
        result = unzip_csv(self._make_zip("informe.CSV", csv_content))
        assert result == csv_content


class TestParseCsvBytes:
    def test_parse_ponto_virgula(self) -> None:
        csv = b"CNPJ_FUNDO;VL_QUOTA\n12345;1.5\n67890;2.0"
        df = parse_csv_bytes(csv)
        assert len(df) == 2
        assert "CNPJ_FUNDO" in df.columns

    def test_todos_campos_como_str(self) -> None:
        csv = b"CNPJ_FUNDO;NR_COTST\n12345;1000"
        df = parse_csv_bytes(csv)
        assert df["NR_COTST"].dtype == object  # str, não int


class TestInformeRecord:
    def test_cnpj_vazio_levanta_erro(self) -> None:
        with pytest.raises(Exception):
            InformeRecord(cnpj_fundo="", dt_comptc=date(2024, 1, 1))

    def test_cnpj_whitespace_levanta_erro(self) -> None:
        with pytest.raises(Exception):
            InformeRecord(cnpj_fundo="   ", dt_comptc=date(2024, 1, 1))

    def test_cnpj_valido_aceito(self) -> None:
        r = InformeRecord(cnpj_fundo="12.345.678/0001-90", dt_comptc=date(2024, 1, 1))
        assert r.cnpj_fundo == "12.345.678/0001-90"

    def test_campos_opcionais_none(self) -> None:
        r = InformeRecord(cnpj_fundo="12345", dt_comptc=date(2024, 1, 1))
        assert r.vl_quota is None


class TestValidateCadastroRows:
    def test_descarta_cnpj_vazio(self) -> None:
        df = pd.DataFrame({"CNPJ_FUNDO": ["12345", "", "67890", None]})
        result = validate_cadastro_rows(df)
        assert len(result) == 2

    def test_preserva_linhas_validas(self) -> None:
        df = pd.DataFrame({"CNPJ_FUNDO": ["12345", "67890"]})
        result = validate_cadastro_rows(df)
        assert len(result) == 2


class TestSafeConversions:
    def test_safe_float_virgula(self) -> None:
        assert _safe_float("1,5") == 1.5

    def test_safe_float_ponto(self) -> None:
        assert _safe_float("1.5") == 1.5

    def test_safe_float_none(self) -> None:
        assert _safe_float(None) is None

    def test_safe_float_nan_string(self) -> None:
        assert _safe_float("nan") is None

    def test_safe_int_float_string(self) -> None:
        assert _safe_int("1000.0") == 1000

    def test_safe_int_none(self) -> None:
        assert _safe_int(None) is None
```

---

## Estratégia de Testes

| Tipo         | Escopo                                         | Ferramentas              | Onde rodar         |
|--------------|------------------------------------------------|--------------------------|--------------------|
| Unit         | `cvm_client.py` — URL, unzip, parse, Pydantic  | pytest                   | Local              |
| Unit         | `loaders_cadastro.py` — upsert SCD Tipo 1      | pytest + mock hook       | Local (skip Airflow)|
| Unit         | `loaders_informe.py` — mês anterior, insert    | pytest + mock hook       | Local (skip Airflow)|
| Integration  | Migration 004 no PostgreSQL real               | `make migrate`           | Container          |
| Integration  | DAG parse na UI Airflow                        | Airflow UI               | Container          |
| E2E (AT-004) | PySpark `--start-year 2024 --end-year 2024`    | `make cvm-hist-load`     | Local              |
| E2E (AT-006) | DAG `@monthly` via trigger manual              | Airflow UI               | Container          |

**Padrão skip Airflow** nos loaders (replicar do BCB):
```python
pytest.importorskip("airflow", reason="Apache Airflow não instalado — rodar dentro do container.")
```

---

## Verificações de Build

| Arquivo                             | Comando                                                     |
|-------------------------------------|-------------------------------------------------------------|
| `004_bronze_cvm.sql`                | `make migrate` — verificar tabelas e partições com `\d+`   |
| `*.py` (todos)                      | `ruff check dags/domain_cvm/ scripts/spark/ tests/domain_cvm/` |
| `cvm_client.py`                     | `python -c "from domain_cvm.ingestion.cvm_client import build_informe_url; print(build_informe_url(2024, 3))"` |
| DAGs                                | Airflow UI — sem erros de import nas duas DAGs              |
| `tests/domain_cvm/`                 | `pytest tests/domain_cvm/ -v`                               |
| AT-003 (ON CONFLICT em partição)    | SQL direto no container antes de escrever código            |

**AT-003 SQL de validação (executar antes do build):**
```sql
-- Validar que ON CONFLICT funciona em tabela particionada
INSERT INTO bronze_cvm.informe_diario
    (cnpj_fundo, dt_comptc, source_url)
VALUES ('TEST123', '2024-01-01', 'test')
ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING;
-- Segunda inserção deve ser silenciosa:
INSERT INTO bronze_cvm.informe_diario
    (cnpj_fundo, dt_comptc, source_url)
VALUES ('TEST123', '2024-01-01', 'test')
ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING;
SELECT COUNT(*) FROM bronze_cvm.informe_diario WHERE cnpj_fundo = 'TEST123'; -- deve retornar 1
```

---

## Revision History

| Versão | Data       | Autor        | Mudanças                                                                      |
|--------|------------|--------------|-------------------------------------------------------------------------------|
| 1.0    | 2026-04-27 | design-agent | Versão inicial — 4 ADRs, 14 arquivos, DDL com 40 colunas, padrões completos   |

---

## Next Step

**Pronto para:** `/build .claude/sdd/features/DESIGN_BRONZE_CVM.md`
