# BRAINSTORM: BRONZE_BCB

> Phase 0 — Exploração e decisões arquiteturais
> Data: 2026-04-22
> Autor: Nilton Coura

---

## Metadata

| Atributo        | Valor                              |
|-----------------|------------------------------------|
| **Feature**     | BRONZE_BCB                         |
| **Domínio**     | domain_macro (BCB)                 |
| **Fase**        | Bronze — Ingestão                  |
| **Próxima fase**| `/define BRAINSTORM_BRONZE_BCB.md` |

---

## Objetivo

Construir a camada Bronze do domínio BCB: ingestão das séries temporais
SELIC (diária), IPCA (mensal) e PTAX (diária) via `python-bcb` para o
PostgreSQL 15, orquestrada por uma DAG Airflow com idempotência completa
e suporte a backfill automático no primeiro run.

---

## Contexto do Projeto

- Infraestrutura (INFRA_BASE) já entregue: PostgreSQL 15 (host port 5433),
  Airflow 2.10.4 standalone, `dags/` vazio, `python-bcb` já na imagem.
- Schema `bronze` existe no `init.sql`. Schemas `bronze_bcb` e `bronze_cvm`
  serão criados por migrations dedicadas, seguindo isolamento Data Mesh.
- `apache-airflow-providers-postgres` precisa ser adicionado ao
  `requirements.txt` — pré-requisito para PostgresHook.

---

## Decisões de Exploração

### Q1 — Carga histórica vs. incremental

**Decisão:** Backfill automático com smart first run.

- Na primeira execução, `get_load_range()` detecta tabela vazia e carrega
  desde a `start_date` configurada por série.
- Nas execuções seguintes, carrega apenas o delta (`max(date) + 1 dia` até hoje).
- `start_date` parametrizável por série:
  - SELIC: `2000-01-01`
  - IPCA: `1994-07-01` (início do Plano Real)
  - PTAX: `1999-01-01` (câmbio flutuante)

**Motivo:** estabelece pipeline funcional com histórico relevante sem
criar uma feature separada de backfill. A lógica é embutida no próprio
pipeline como "smart first run".

---

### Q2 — Isolamento de schema

**Decisão:** Schema dedicado `bronze_bcb` — padrão Data Mesh.

- Cada domínio tem seu próprio schema: `bronze_bcb`, `bronze_cvm` (futuro).
- Permite `GRANT` granular por domínio (`GRANT USAGE ON SCHEMA bronze_bcb TO role_bcb`).
- Evita colisão de nomes quando CVM entrar.
- Schema criado via migration SQL dedicada:
  `docker/postgres/migrations/001_bronze_bcb.sql`

**Alternativa descartada:** `bronze.bcb_selic_daily` — schema genérico viola
isolamento do Data Mesh e dificulta GRANT por domínio.

---

### Q3 — Design da DAG

**Decisão:** Uma DAG `dag_bronze_bcb` com 3 tasks paralelas, schedule diário.

```
dag_bronze_bcb  (schedule: @daily)
├── ingest_selic_daily    ← executa todo dia útil
├── ingest_ipca_monthly   ← executa todo dia; skip se mês já gravado
└── ingest_ptax_daily     ← executa todo dia útil
```

- IPCA tem lógica de idempotência por mês: verifica se já existe registro
  para o mês de referência corrente antes de tentar gravar. Finaliza sem
  erro (`AirflowSkipException`) se positivo.
- Todas as tasks compartilham `get_load_range()` para o smart first run.

**Alternativa descartada:** DAGs separadas por série — overhead de gestão
sem benefício real no MVP. Coesão de domínio favorece DAG única.

---

## Grounding — Formato `python-bcb`

Confirmado via execução real:

| Atributo            | Valor                                          |
|---------------------|------------------------------------------------|
| Tipo de retorno     | `pandas.DataFrame`                             |
| Índice              | `DatetimeIndex` (`datetime64[us]`, name=`Date`) |
| Coluna de valor     | Nome igual à chave do dict passado (ex: `SELIC`) |
| Dtype do valor      | `float64`                                      |
| SELIC/PTAX          | Diária, apenas dias úteis (pula fins de semana) |
| IPCA                | Mensal, data sempre no dia 1 do mês            |

Conversão necessária: `DatetimeIndex → date` com `.date()` antes do INSERT.

---

## Abordagem Selecionada

### Abordagem A: PythonOperator + PostgresHook ⭐

Tasks como `PythonOperator` usando `PostgresHook(postgres_conn_id='finlake_postgres')`
do provider `apache-airflow-providers-postgres`. Upsert via
`INSERT ... ON CONFLICT (date) DO NOTHING`.

**Prós:**
- Idiomático no Airflow — conexão gerenciada pela UI e por env vars.
- Rotação de credenciais sem alterar código.
- Testável com mock do hook.
- Sem dependência extra além do provider oficial.

**Contras:**
- Requer `apache-airflow-providers-postgres` no `requirements.txt`
  (ausente no estado atual).

**Abordagens descartadas:**
- `psycopg2` direto: contorna o gerenciamento de conexões do Airflow,
  duplica lógica que o provider já entrega.
- `pandas.to_sql()`: sem idempotência nativa — precisaria de DELETE + INSERT
  manual para evitar duplicatas no reprocessamento.

---

## DDL — Tabelas Bronze

```sql
-- docker/postgres/migrations/001_bronze_bcb.sql

CREATE SCHEMA IF NOT EXISTS bronze_bcb;

CREATE TABLE IF NOT EXISTS bronze_bcb.selic_daily (
    date         DATE           NOT NULL,
    valor        NUMERIC(10,6)  NOT NULL,
    ingested_at  TIMESTAMP      NOT NULL DEFAULT NOW(),
    source_api   VARCHAR(50)    NOT NULL DEFAULT 'BCB_SGS',
    PRIMARY KEY  (date)
);

CREATE TABLE IF NOT EXISTS bronze_bcb.ipca_monthly (
    date         DATE           NOT NULL,  -- sempre dia 1 do mês
    valor        NUMERIC(6,4)   NOT NULL,
    ingested_at  TIMESTAMP      NOT NULL DEFAULT NOW(),
    source_api   VARCHAR(50)    NOT NULL DEFAULT 'BCB_SGS',
    PRIMARY KEY  (date)
);

CREATE TABLE IF NOT EXISTS bronze_bcb.ptax_daily (
    date         DATE           NOT NULL,
    valor        NUMERIC(10,4)  NOT NULL,
    ingested_at  TIMESTAMP      NOT NULL DEFAULT NOW(),
    source_api   VARCHAR(50)    NOT NULL DEFAULT 'BCB_SGS',
    PRIMARY KEY  (date)
);
```

**Colunas de auditoria (todas as tabelas):**
- `ingested_at`: rastreabilidade temporal da ingestão.
- `source_api DEFAULT 'BCB_SGS'`: discriminador de origem. Essencial quando
  CVM entrar no Data Mesh com `source_api = 'CVM_DADOS'`.

---

## Estrutura de Arquivos

```
dags/
└── domain_bcb/
    ├── __init__.py
    ├── dag_bronze_bcb.py          ← definição da DAG + tasks
    └── ingestion/
        ├── __init__.py
        ├── bcb_client.py          ← wrapper python-bcb + get_load_range()
        └── loaders.py             ← ingest_selic, ingest_ipca, ingest_ptax
```

---

## Lógica de Idempotência

### `get_load_range(table, start_date_config)` → `tuple[date, date] | None`

```python
# Tabela vazia  → retorna (start_date_config, hoje)  [backfill]
# Tabela com dados → retorna (max(date) + 1 dia, hoje)  [incremental]
# IPCA: mês corrente já gravado → retorna None  [skip]
```

### INSERT idempotente

```sql
INSERT INTO bronze_bcb.selic_daily (date, valor)
VALUES (%s, %s)
ON CONFLICT (date) DO NOTHING;
```

Reprocessamento seguro: executar a mesma DAG duas vezes no mesmo dia
não duplica registros.

---

## Pré-requisitos (Bloqueantes)

### 1. `apache-airflow-providers-postgres` no `requirements.txt`

Adicionar à linha de dependências em `docker/airflow/requirements.txt`.
Necessário para `PostgresHook`. Rebuild da imagem requerido.

### 2. `AIRFLOW_CONN_FINLAKE_POSTGRES` no `.env` e `compose.airflow.yml`

**Crítico:** sem esta variável, o `PostgresHook` não encontra a conexão
e todas as tasks falharão em runtime.

Formato da connection string do Airflow:
```
postgresql://postgres:<PASSWORD>@postgres:5432/finlake
```

Adições necessárias:

**`.env.example`:**
```dotenv
# Airflow Connections
AIRFLOW_CONN_FINLAKE_POSTGRES=postgresql://postgres:<POSTGRES_PASSWORD>@postgres:5432/finlake
```

**`docker/compose.airflow.yml`** (seção `environment` do serviço airflow):
```yaml
AIRFLOW_CONN_FINLAKE_POSTGRES: "${AIRFLOW_CONN_FINLAKE_POSTGRES}"
```

> Nota: dentro da rede Docker, o host é `postgres` (nome do serviço),
> não `localhost`. A porta é `5432` (interna), não `5433` (host).

---

## YAGNI — Features Removidas

| Feature                               | Decisão    | Motivo                                                                 |
|---------------------------------------|------------|------------------------------------------------------------------------|
| Parquet files paralelos ao PostgreSQL | Removido   | Deferido para feature separada. DuckDB lê direto do Postgres no MVP.  |
| Tabela de controle `pipeline_runs`    | Removido   | Airflow já persiste execução, duração e status por task nativamente.   |
| Great Expectations na Bronze          | Removido   | Validação é concern da camada Silver. Bronze recebe dados brutos.      |
| Alertas e-mail/Slack em falha         | Removido   | Configuração de destino de alerta é concern de operações, não pipeline.|

---

## Requisitos Rascunho para `/define`

### Funcionais

- **RF-01:** DAG `dag_bronze_bcb` com schedule `@daily` e 3 tasks paralelas.
- **RF-02:** `get_load_range()` detecta tabela vazia e carrega desde `start_date`
  configurado por série (SELIC: 2000, IPCA: 1994-07, PTAX: 1999).
- **RF-03:** Ingestão incremental nas execuções seguintes: carrega apenas delta
  a partir de `max(date) + 1`.
- **RF-04:** Task `ingest_ipca_monthly` verifica mês corrente antes de gravar;
  emite `AirflowSkipException` se registro já existe.
- **RF-05:** Upsert via `INSERT ... ON CONFLICT (date) DO NOTHING` em todas as tasks.
- **RF-06:** Schema `bronze_bcb` criado via migration `001_bronze_bcb.sql`.
- **RF-07:** Colunas de auditoria `ingested_at` e `source_api` em todas as tabelas.

### Não-Funcionais

- **RNF-01:** Reprocessamento da DAG no mesmo dia não duplica registros.
- **RNF-02:** Falha numa task não cancela as outras (tasks independentes).
- **RNF-03:** Conexão PostgreSQL gerenciada pelo Airflow via `PostgresHook`.
- **RNF-04:** Sem credenciais hardcoded — tudo via variáveis de ambiente.

### Pré-requisitos

- **PRE-01:** `apache-airflow-providers-postgres` adicionado ao `requirements.txt`.
- **PRE-02:** `AIRFLOW_CONN_FINLAKE_POSTGRES` declarado no `.env` e injetado
  no container Airflow via `compose.airflow.yml`.

---

## Próximos Passos

```
/define .claude/sdd/features/BRAINSTORM_BRONZE_BCB.md
```
