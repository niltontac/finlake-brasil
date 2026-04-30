# BRAINSTORM: BRONZE_CVM

> Phase 0 — Exploração e decisões arquiteturais
> Data: 2026-04-26
> Autor: Nilton Coura

---

## Metadata

| Atributo         | Valor                               |
|------------------|-------------------------------------|
| **Feature**      | BRONZE_CVM                          |
| **Domínio**      | domain_funds (CVM)                  |
| **Fase**         | Bronze — Ingestão                   |
| **Próxima fase** | `/define BRAINSTORM_BRONZE_CVM.md`  |

---

## Objetivo

Construir a camada Bronze do domínio CVM: ingestão do cadastro de fundos
(`cad_fi.csv`) e do informe diário (`inf_diario_fi_YYYYMM.zip`) do portal
de dados abertos da CVM para o PostgreSQL 15, com duas estratégias de
carga complementares — PySpark para bulk histórico e Airflow para delta
incremental mensal.

---

## Contexto do Projeto

- Domínio BCB (domain_macro) completo: BRONZE → SILVER → GOLD → METABASE.
- Stack CVM segue os mesmos princípios do BCB: `PostgresHook`, migrations SQL,
  idempotência via `ON CONFLICT`, colunas de auditoria `ingested_at`/`source_url`.
- PySpark está no stack declarado em `CLAUDE.md` especificamente para dados
  históricos bulk da CVM — este é o caso de uso previsto.
- Schema `bronze_cvm` seguirá isolamento Data Mesh: nenhum objeto compartilhado
  com `bronze_bcb`.

---

## Grounding — Formato Real dos Arquivos CVM

Dados validados com download real dos arquivos antes do brainstorm.

### Cadastro (`cad_fi.csv`)

| Atributo      | Valor                                   |
|---------------|-----------------------------------------|
| Separador     | `;`                                     |
| Encoding      | ISO-8859-1 (latin1)                     |
| Line endings  | CRLF                                    |
| Colunas       | 40 (documentação oficial subestima)     |
| Atualização   | Diária, arquivo único                   |
| Registros     | ~30k fundos                             |

Colunas principais confirmadas: `TP_FUNDO`, `CNPJ_FUNDO`, `DENOM_SOCIAL`,
`DT_REG`, `DT_CONST`, `CD_CVM`, `DT_CANCEL`, `SIT`, `DT_INI_SIT`,
`DT_INI_ATIV`, `CLASSE`, `RENTAB_FUNDO`, `CONDOM`, `FUNDO_COTAS`,
`TAXA_PERFM`, `TAXA_ADM`, `VL_PATRIM_LIQ`, `DT_PATRIM_LIQ`,
`CNPJ_ADMIN`, `ADMIN`, `CNPJ_GESTOR`, `GESTOR`, `CNPJ_AUDITOR`,
`AUDITOR`, `CNPJ_CUSTODIANTE`, `CLASSE_ANBIMA`.

### Informe Diário (`inf_diario_fi_YYYYMM.zip`)

| Atributo      | Valor                                        |
|---------------|----------------------------------------------|
| Formato       | **ZIP contendo CSV** (não CSV direto)        |
| Separador     | `;`                                          |
| Encoding      | ISO-8859-1 (assumido padrão CVM)             |
| Colunas       | 9 (documentação oficial indica 8)            |
| Tamanho       | ~48 MB descomprimido por mês                 |

Colunas confirmadas (coluna extra `TP_FUNDO` não documentada):

| Coluna          | Tipo SQL          |
|-----------------|-------------------|
| `TP_FUNDO`      | `VARCHAR(10)`     |
| `CNPJ_FUNDO`    | `VARCHAR(18)`     |
| `DT_COMPTC`     | `DATE`            |
| `VL_TOTAL`      | `NUMERIC(18,6)`   |
| `VL_QUOTA`      | `NUMERIC(18,8)`   |
| `VL_PATRIM_LIQ` | `NUMERIC(18,6)`   |
| `CAPTC_DIA`     | `NUMERIC(18,6)`   |
| `RESG_DIA`      | `NUMERIC(18,6)`   |
| `NR_COTST`      | `INTEGER`         |

### Estrutura de URLs — CRÍTICO

A CVM mantém **duas estruturas de URL distintas**. O extrator deve tratar ambas:

| Período     | Estrutura                                           | Granularidade |
|-------------|-----------------------------------------------------|---------------|
| 2000–2020   | `DADOS/HIST/inf_diario_fi_{YYYY}.zip`               | Anual         |
| 2021–atual  | `DADOS/inf_diario_fi_{YYYYMM}.zip`                  | Mensal        |

Implicações:
- PySpark bulk: lógica bifurcada por período (`HIST/` vs `DADOS/`)
- Airflow delta: apenas `DADOS/` mensal — sempre mês anterior
- Descompressão em memória obrigatória: `zipfile.ZipFile` + `io.BytesIO`

---

## Decisões de Exploração

### Q1 — Estratégia de Carga Histórica

**Decisão:** PySpark para bulk histórico + Airflow para delta mensal.

- **PySpark:** script configurável com `--start-year` / `--end-year`.
  Carrega todos os ZIPs do intervalo em paralelo via JDBC → PostgreSQL.
  Modo `append` — a PK composta no banco garante deduplicação.
- **Airflow:** DAG `dag_bronze_cvm_informe` com `schedule=@monthly`,
  `catchup=False`. Processa apenas o mês anterior (sempre `DADOS/`).

**Separação de responsabilidades:**
```
PySpark  →  bulk histórico (2000–2024 ou janela configurável)
Airflow  →  delta mensal incremental (mês N-1, a partir do momento de deploy)
```

**Alternativas descartadas:**
- Airflow puro com catchup: 250+ runs sequenciais, horas para completar backfill.
- Script Python one-shot: mais simples que PySpark mas sem paralelismo; desperdício
  do componente já disponível no stack.

---

### Q2 — Idempotência do Informe Diário

**Decisão:** Primary key composta `(cnpj_fundo, dt_comptc)` +
`ON CONFLICT DO NOTHING`.

```sql
PRIMARY KEY (cnpj_fundo, dt_comptc)

INSERT INTO bronze_cvm.informe_diario (cnpj_fundo, dt_comptc, ...)
VALUES (...)
ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING;
```

**Por quê:** mesma filosofia do BCB — a garantia fica no banco. Funciona
identicamente para PySpark (JDBC append) e Airflow (PostgresHook). Não
é necessário coordenação entre os dois sistemas de carga.

**Alternativas descartadas:**
- Partição com DELETE + INSERT: risco de janela de dados ausentes entre as
  duas operações em caso de falha.
- Tabela de controle `pipeline_runs`: lógica extra que o banco já oferece
  via constraint de PK.

---

### Q3 — Cadastro: SCD Tipo 1

**Decisão:** SCD Tipo 1 no Bronze — `ON CONFLICT (cnpj_fundo) DO UPDATE`.

```sql
INSERT INTO bronze_cvm.cadastro (cnpj_fundo, denom_social, sit, ...)
ON CONFLICT (cnpj_fundo) DO UPDATE SET
    denom_social  = EXCLUDED.denom_social,
    sit           = EXCLUDED.sit,
    dt_ini_sit    = EXCLUDED.dt_ini_sit,
    updated_at    = NOW();
```

**Por quê:** Bronze é espelho do estado atual da fonte. A CVM entrega o
arquivo com o estado corrente de todos os fundos — o Bronze espelha isso.
Histórico de mudanças (ex: fundo que mudou de situação) é concern da
**Silver**, implementado como SCD Tipo 2 em model dbt, se necessário.

**Alternativas descartadas:**
- SCD Tipo 2 no Bronze: complexidade desproporcional; detectar mudança é
  responsabilidade da Silver, não da ingestão bruta.
- Append puro com `ingested_at`: ~10M linhas/ano para dados que mudam pouco;
  impõe deduplicação complexa na Silver.

---

### Q4 — Particionamento da Tabela `informe_diario`

**Decisão:** `PARTITION BY RANGE (dt_comptc)` com estratégia híbrida:

```sql
CREATE TABLE bronze_cvm.informe_diario (...)
PARTITION BY RANGE (dt_comptc);

-- Bloco histórico imutável (nunca recebe novos dados)
CREATE TABLE bronze_cvm.informe_diario_hist
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2000-01-01') TO ('2021-01-01');

-- Partições anuais individuais para dados recentes
CREATE TABLE bronze_cvm.informe_diario_2021
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2021-01-01') TO ('2022-01-01');
-- ... 2022, 2023, 2024, 2025, 2026
```

**Racional da estratégia híbrida:**
- `informe_diario_hist` (2000–2020): bloco imutável, nunca recebe novos dados,
  não precisa de granularidade maior.
- Partições anuais 2021+: cada ano recebe carga incremental mensal do Airflow;
  granularidade individual permite operações de manutenção por ano.
- Total: ~7 partições gerenciáveis vs. 250+ se fosse mensal.

**Alternativa descartada:**
- Particionamento mensal: ~250 partições, DDL de criação precisa ser automatizado,
  overhead de gerenciamento desproporcional ao benefício no contexto local.

---

### Q5 — Relacionamento no Bronze

**Decisão:** Duas tabelas independentes.

```
bronze_cvm.cadastro          →  ~30k registros, SCD Tipo 1
bronze_cvm.informe_diario    →  dezenas de M de linhas, particionado
```

**Por quê:** Bronze espelha a fonte. A CVM entrega dois arquivos separados —
armazenamos dois objetos separados. `JOIN` entre cadastro e informe é
responsabilidade da **Silver** como model dbt.

**Benefícios:**
- Falha na carga do cadastro não bloqueia a carga do informe (cargas independentes).
- Sem redundância: dados cadastrais não replicados em cada linha do informe.
- Consistência histórica: se um fundo mudar de situação, o histórico do informe
  não fica "contaminado" com dados cadastrais desatualizados.

---

## Arquitetura da Solução

### Estrutura de Arquivos

```
dags/
└── domain_cvm/
    ├── __init__.py
    ├── dag_bronze_cvm_cadastro.py     ← @daily, 1 task
    ├── dag_bronze_cvm_informe.py      ← @monthly, 1 task (mês anterior)
    └── ingestion/
        ├── __init__.py
        ├── cvm_client.py              ← download ZIP/CSV, unzip BytesIO, parse latin1
        ├── loaders_cadastro.py        ← ingest_cadastro (callable Airflow)
        └── loaders_informe.py         ← ingest_informe_mensal (callable Airflow)

scripts/
└── spark/
    └── historical_load_cvm.py         ← PySpark bulk, args: --start-year --end-year

docker/
└── postgres/
    └── migrations/
        └── 004_bronze_cvm.sql         ← schema + tabelas + partições

tests/
└── domain_cvm/
    ├── __init__.py
    ├── test_cvm_client.py
    ├── test_loaders_cadastro.py
    └── test_loaders_informe.py
```

### Fluxo de Dados

```
CVM Portal (dados.cvm.gov.br)
│
├── cad_fi.csv ──────────────────────────────────────────────────────────┐
│   (daily, ~30k rows, latin1, semicolon)                                │
│                                                                         ▼
│                                                          Airflow @daily
│                                                          dag_bronze_cvm_cadastro
│                                                          └── cvm_client.py
│                                                              └── postgres
│                                                                  bronze_cvm.cadastro
│                                                                  (SCD Tipo 1)
│
└── inf_diario_fi_*.zip ─────────────────────────────────────────────────┐
    │                                                                     │
    ├── BULK (2000–2024)                         ├── DELTA (mês anterior)│
    │   PySpark historical_load_cvm.py           │   Airflow @monthly    │
    │   --start-year 2000 --end-year 2024        │   dag_bronze_cvm_informe
    │   Paralelo por arquivo ZIP                 │                       │
    │   JDBC append → PostgreSQL                 │   cvm_client.py       │
    │                                            │   └── PostgresHook    │
    └────────────────────────────────────────────┴───────────────────────┘
                                                         ▼
                                            bronze_cvm.informe_diario
                                            (PARTITIONED BY RANGE dt_comptc)
                                            ├── informe_diario_hist  (2000-2020)
                                            ├── informe_diario_2021
                                            ├── informe_diario_2022
                                            ├── ...
                                            └── informe_diario_2026
```

### Lógica de URL no `cvm_client.py`

```python
def build_informe_url(year: int, month: int) -> str:
    base = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS"
    if year <= 2020:
        return f"{base}/HIST/inf_diario_fi_{year}.zip"
    return f"{base}/inf_diario_fi_{year}{month:02d}.zip"
```

### Idempotência — Dois Caminhos, Uma Garantia

```
PySpark  →  JDBC append  →  PK (cnpj_fundo, dt_comptc)  →  ON CONFLICT DO NOTHING
Airflow  →  PostgresHook →  PK (cnpj_fundo, dt_comptc)  →  ON CONFLICT DO NOTHING
```

Reprocessar qualquer carga (PySpark ou Airflow) não duplica registros.

---

## DDL — Rascunho

```sql
-- 004_bronze_cvm.sql

CREATE SCHEMA IF NOT EXISTS bronze_cvm;

-- Cadastro de Fundos (SCD Tipo 1)
CREATE TABLE IF NOT EXISTS bronze_cvm.cadastro (
    cnpj_fundo      VARCHAR(18)   NOT NULL,
    tp_fundo        VARCHAR(100),
    denom_social    VARCHAR(200),
    dt_reg          DATE,
    dt_const        DATE,
    cd_cvm          VARCHAR(20),
    dt_cancel       DATE,
    sit             VARCHAR(80),
    dt_ini_sit      DATE,
    dt_ini_ativ     DATE,
    classe          VARCHAR(100),
    rentab_fundo    VARCHAR(200),
    condom          VARCHAR(20),
    fundo_cotas     VARCHAR(1),
    taxa_perfm      NUMERIC(10,4),
    taxa_adm        NUMERIC(10,4),
    vl_patrim_liq   NUMERIC(18,6),
    dt_patrim_liq   DATE,
    cnpj_admin      VARCHAR(18),
    admin           VARCHAR(200),
    cnpj_gestor     VARCHAR(18),
    gestor          VARCHAR(200),
    cnpj_auditor    VARCHAR(18),
    auditor         VARCHAR(200),
    cnpj_custodiante VARCHAR(18),
    classe_anbima   VARCHAR(100),
    ingested_at     TIMESTAMP     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP     NOT NULL DEFAULT NOW(),
    source_url      VARCHAR(300)  NOT NULL,
    CONSTRAINT cadastro_pkey PRIMARY KEY (cnpj_fundo)
);

-- Informe Diário (particionado por ano)
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

-- Partição histórica imutável (2000–2020)
CREATE TABLE IF NOT EXISTS bronze_cvm.informe_diario_hist
    PARTITION OF bronze_cvm.informe_diario
    FOR VALUES FROM ('2000-01-01') TO ('2021-01-01');

-- Partições anuais recentes
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

## YAGNI — Features Removidas

| Feature                                  | Decisão    | Motivo                                                              |
|------------------------------------------|------------|---------------------------------------------------------------------|
| Parquet files paralelos ao PostgreSQL    | Removido   | Deferido — DuckDB lê direto do Postgres no MVP                     |
| Tabela `pipeline_runs` de controle       | Removido   | Airflow persiste execução nativamente; PySpark usa logging          |
| Great Expectations no Bronze             | Removido   | Validação é concern da Silver                                       |
| Particionamento mensal do informe        | Removido   | Anual é suficiente — ~22 vs ~250 partições, sem ganho real local    |
| SCD Tipo 2 no Bronze                     | Removido   | Silver resolve com dbt model se necessário                          |
| Download paralelo de ZIPs no Airflow     | Removido   | Paralelismo é responsabilidade do PySpark, não do Airflow           |
| Schema de validação Pydantic exaustivo   | Simplificado | Validar tipos críticos (CNPJ, datas, valores) — não todas as 40 colunas do cadastro |

---

## Pré-requisitos (Bloqueantes)

### 1. Dependências Python no container Airflow
```
requests          # download HTTP dos ZIPs
pandas            # parse CSV
pydantic>=2.0     # validação
apache-airflow-providers-postgres  # PostgresHook (já presente do BCB)
```

### 2. PySpark com JDBC driver PostgreSQL
```
spark.jars  →  postgresql-42.x.jar
```

### 3. Migration `004_bronze_cvm.sql` executada antes do primeiro deploy

### 4. `AIRFLOW_CONN_FINLAKE_POSTGRES` (já configurada no BCB — reutilizar)

---

## Requisitos Rascunho para `/define`

### Funcionais

- **RF-01:** DAG `dag_bronze_cvm_cadastro` com `schedule=@daily`, 1 task: `ingest_cadastro`.
- **RF-02:** `ingest_cadastro` baixa `cad_fi.csv` (latin1), decodifica para UTF-8,
  faz upsert SCD Tipo 1 via `ON CONFLICT (cnpj_fundo) DO UPDATE`.
- **RF-03:** DAG `dag_bronze_cvm_informe` com `schedule=@monthly`, `catchup=False`,
  1 task: `ingest_informe_mensal`.
- **RF-04:** `ingest_informe_mensal` determina o mês anterior, constrói URL `DADOS/`,
  baixa ZIP, descomprime em memória, insere via `ON CONFLICT (cnpj_fundo, dt_comptc) DO NOTHING`.
- **RF-05:** `historical_load_cvm.py` (PySpark) aceita `--start-year` / `--end-year`,
  itera anos/meses, usa lógica de URL bifurcada (`HIST/` vs `DADOS/`), carrega via JDBC.
- **RF-06:** `cvm_client.py` centraliza: `build_informe_url()`, download ZIP,
  unzip em memória (`BytesIO`), parse CSV com separador `;` e encoding latin1.
- **RF-07:** Validação Pydantic em `cvm_client.py` para tipos críticos antes de qualquer insert.
- **RF-08:** Schema `bronze_cvm` criado via migration `004_bronze_cvm.sql`, idempotente.
- **RF-09:** Colunas de auditoria `ingested_at` e `source_url` em todas as tabelas.

### Não-Funcionais

- **RNF-01:** Reprocessamento de qualquer carga (PySpark ou Airflow) não duplica registros.
- **RNF-02:** Encoding ISO-8859-1 da CVM transparente para consumidores — PostgreSQL armazena UTF-8.
- **RNF-03:** Script PySpark configurável por janela de anos — sem hardcode de datas.
- **RNF-04:** Sem credenciais hardcoded — JDBC URL via variável de ambiente.

---

## Próximos Passos

```
/define .claude/sdd/features/BRAINSTORM_BRONZE_CVM.md
```
