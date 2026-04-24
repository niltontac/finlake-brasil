# BRAINSTORM: SILVER_BCB

> Phase 0 — Exploração e decisões arquiteturais
> Data: 2026-04-24
> Autor: Nilton Coura

---

## Metadata

| Atributo         | Valor                               |
|------------------|-------------------------------------|
| **Feature**      | SILVER_BCB                          |
| **Domínio**      | domain_macro (BCB)                  |
| **Fase**         | Silver — Transformação e Validação  |
| **Upstream**     | BRONZE_BCB (shipped 2026-04-23)     |
| **Próxima fase** | `/define BRAINSTORM_SILVER_BCB.md`  |

---

## Objetivo

Construir a camada Silver do domínio BCB: transformação, validação e
normalização das séries SELIC, IPCA e PTAX vindas da `bronze_bcb` para o
schema `silver_bcb`, via modelos dbt-core. Esta feature também entrega o
**setup inicial do dbt no projeto FinLake Brasil** — incluindo
`dbt_project.yml`, `profiles.yml` e estrutura `transform/`.

---

## Contexto do Projeto

- Bronze populada e operacional: 6.606 SELIC + 381 IPCA + 6.856 PTAX
  registros no schema `bronze_bcb` (PostgreSQL 15, porta 5433).
- dbt-core listado na stack (`CLAUDE.md`) mas **sem projeto inicializado**.
  Esta feature é o greenfield dbt do FinLake Brasil.
- DuckDB previsto para Gold layer (processamento analítico cross-domain).
  Silver permanece em PostgreSQL — consistência com Bronze.
- Airflow 2.10.4 standalone, `dag_bronze_bcb` operacional com schedule `@daily`.

---

## Grounding — Dados Reais da Bronze

Confirmado via query em `bronze_bcb`:

| Série | Último valor | Tipo armazenado | Unidade real     | Último registro |
|-------|-------------|-----------------|------------------|-----------------|
| SELIC | `0.054266`  | NUMERIC(10,6)   | % a.d.           | 2026-04-22      |
| IPCA  | `0.8800`    | NUMERIC(6,4)    | % mensal         | 2026-03-01      |
| PTAX  | `4.9653`    | NUMERIC(10,4)   | R$/USD           | 2026-04-22      |

**Achado crítico:** `valor = 0.054266` para SELIC é **% ao dia**, não decimal
puro. A fórmula de anualização correta é `(power(1 + valor/100.0, 252) - 1) * 100`,
produzindo `~14.65% a.a.` — alinhado com SELIC meta atual (~14.75% a.a.).
A fórmula `(1 + valor)^252 - 1` (sem divisão por 100) produziria resultado
incorreto com os valores armazenados.

**Comportamento PTAX LAG:** `bronze_bcb.ptax_daily` contém apenas dias úteis.
`LAG(valor, 1) OVER (ORDER BY date)` naturalmente retorna o dia útil anterior
sem tratamento especial de gaps — fins de semana e feriados simplesmente não
existem na tabela. Documentar como nota no `schema.yml`.

---

## Decisões de Exploração

### Q1 — Transformações na Silver

**Decisão:** Limpeza + indicadores derivados por série (opção b).

Silver vai além da tipagem pura sem invadir o território da Gold
(que fará cruzamentos entre SELIC, IPCA e PTAX).

| Série | Coluna original → Silver | Coluna derivada        |
|-------|--------------------------|------------------------|
| SELIC | `valor → taxa_diaria`   | `taxa_anual`           |
| IPCA  | `valor → variacao_mensal`| `acumulado_12m`        |
| PTAX  | `valor → taxa_cambio`   | `variacao_diaria_pct`  |

**Deferido para Gold:** `indice_base100` do IPCA — cálculo cumulativo desde
1994-07-01, análise histórica de longo prazo, concern analítico que depende
do range histórico completo como ponto de partida.

---

### Q2 — Localização do projeto dbt

**Decisão:** Diretório `transform/` na raiz do repositório.

Nome semântico (responsabilidade), não acidental (ferramenta). Quando DuckDB
entrar para Gold ou qualquer outra engine de transformação futura, o diretório
continua coerente. `dbt/` amarraria o nome à ferramenta atual.

**Alternativa descartada:** dbt na raiz do projeto — polui o root com
`dbt_project.yml`, `target/`, `logs/` junto a `docker-compose.yml`.

---

### Q3 — Execução do dbt no Airflow

**Decisão:** `BashOperator` chamando `dbt run --select domain_bcb --target airflow`.

Para 3 modelos no MVP, `astronomer-cosmos` (~50 dependências extras) é
over-engineering sem benefício de observabilidade justificado. Migração para
cosmos documentada como recomendação quando projeto dbt crescer para 10+ modelos
com domínio CVM.

**Orquestração cross-DAG:** `dag_silver_bcb` com `ExternalTaskSensor`
aguardando `dag_bronze_bcb` — downstream conhece upstream, nunca o contrário.
Direção de dependência alinhada com Data Mesh. `TriggerDagRunOperator` foi
considerado e descartado porque inverteria o fluxo (Bronze "saberia" sobre Silver).

---

## Fórmulas Derivadas — Validadas com Dados Reais

### SELIC → `taxa_anual`

```sql
(power(1 + taxa_diaria / 100.0, 252) - 1) * 100
-- Convenção BCB: 252 dias úteis/ano
-- Exemplo: (power(1.00054266, 252) - 1) * 100 ≈ 14.65% a.a.
-- Tipo: NUMERIC(8,4)
```

### IPCA → `acumulado_12m`

```sql
(
  exp(
    sum(ln(1 + variacao_mensal / 100.0))
    over (order by date rows between 11 preceding and current row)
  ) - 1
) * 100
-- Produto encadeado via EXP(SUM(LN())) — fórmula exata de composição
-- NULL nos primeiros 11 meses (1994-07 a 1995-05) — comportamento esperado
-- Tipo: NUMERIC(8,4)
```

### PTAX → `variacao_diaria_pct`

```sql
(taxa_cambio / lag(taxa_cambio, 1) over (order by date) - 1) * 100
-- lag retorna dia útil anterior naturalmente (só dias úteis na Bronze)
-- NULL no primeiro registro histórico (1999-01-04) — comportamento esperado
-- Exemplo: (4.9653 / 4.9844 - 1) * 100 = -0.38%
-- Tipo: NUMERIC(8,4)
```

**Convenção Silver:** todas as colunas derivadas expressas em `%` como
`NUMERIC(8,4)` — consistência de unidades na camada de consumo.

---

## Abordagem Selecionada

### Abordagem A: dbt-postgres + `silver_bcb` no PostgreSQL ⭐

dbt conecta ao mesmo PostgreSQL da Bronze, escreve no schema `silver_bcb`.
`profiles.yml` com dois targets:

```yaml
finlake:
  target: dev
  outputs:
    dev:      # desenvolvimento local
      type: postgres
      host: localhost
      port: 5433
      ...
    airflow:  # execução no container
      type: postgres
      host: postgres
      port: 5432
      ...
```

**Alternativa descartada:** dbt-duckdb gravando no `finlake.duckdb` — viola
decisão arquitetural do `CLAUDE.md` onde DuckDB é camada Gold.

---

## Schema das Tabelas Silver

### `silver_bcb.selic_daily`

| Coluna              | Tipo          | Origem           | Notas                          |
|---------------------|---------------|------------------|--------------------------------|
| `date`              | DATE PK       | bronze           |                                |
| `taxa_diaria`       | NUMERIC(10,6) | `valor`          | % a.d. (sem alteração)        |
| `taxa_anual`        | NUMERIC(8,4)  | derivada         | % a.a. via power(252)         |
| `source_api`        | VARCHAR(50)   | bronze           | `'BCB_SGS'`                   |
| `transformed_at`    | TIMESTAMP     | `current_timestamp` | SELECT do modelo dbt       |

### `silver_bcb.ipca_monthly`

| Coluna              | Tipo          | Origem           | Notas                          |
|---------------------|---------------|------------------|--------------------------------|
| `date`              | DATE PK       | bronze           | Primeiro dia do mês           |
| `variacao_mensal`   | NUMERIC(6,4)  | `valor`          | % mensal (sem alteração)      |
| `acumulado_12m`     | NUMERIC(8,4)  | derivada         | NULL primeiros 11 meses       |
| `source_api`        | VARCHAR(50)   | bronze           |                                |
| `transformed_at`    | TIMESTAMP     | `current_timestamp` |                            |

### `silver_bcb.ptax_daily`

| Coluna                | Tipo          | Origem           | Notas                          |
|-----------------------|---------------|------------------|--------------------------------|
| `date`                | DATE PK       | bronze           |                                |
| `taxa_cambio`         | NUMERIC(10,4) | `valor`          | R$/USD (sem alteração)        |
| `variacao_diaria_pct` | NUMERIC(8,4)  | derivada         | NULL no primeiro registro     |
| `source_api`          | VARCHAR(50)   | bronze           |                                |
| `transformed_at`      | TIMESTAMP     | `current_timestamp` |                            |

---

## Estrutura de Arquivos

```
transform/
├── dbt_project.yml
├── profiles.yml
└── models/
    └── domain_bcb/
        ├── sources.yml        ← fonte bronze_bcb + freshness config
        ├── schema.yml         ← docs + testes dbt + notas de comportamento
        ├── selic_daily.sql
        ├── ipca_monthly.sql
        └── ptax_daily.sql

dags/domain_bcb/
└── dag_silver_bcb.py          ← ExternalTaskSensor + BashOperator

docker/compose.airflow.yml     ← adicionar bind mount ./transform:/opt/airflow/transform
docker/airflow/requirements.txt ← adicionar dbt-postgres
```

---

## DAG `dag_silver_bcb`

```
dag_silver_bcb  (schedule: @daily, catchup=False)
│
├── wait_bronze_bcb
│     ExternalTaskSensor
│       external_dag_id  = 'dag_bronze_bcb'
│       external_task_id = None        (aguarda toda a DAG)
│       timeout          = 3600s
│       mode             = 'reschedule' (não bloqueia worker slot)
│
└── dbt_run_silver_bcb
      BashOperator
        bash_command = 'dbt run --select domain_bcb --target airflow'
        cwd          = '/opt/airflow/transform'
        env          = {POSTGRES_USER, POSTGRES_PASSWORD via env vars}
```

---

## YAGNI — Features Removidas

| Feature                       | Decisão    | Motivo                                                              |
|-------------------------------|------------|---------------------------------------------------------------------|
| `dbt docs generate/serve`     | Removido   | Documentação de portfólio, não pipeline de dados. Deferido.        |
| `dbt snapshot` (SCD Type 2)   | Removido   | Séries temporais são imutáveis — não há "versão" de valor histórico.|
| `dbt seeds`                   | Removido   | Nenhum dado de referência CSV no domínio BCB.                      |
| Outlier detection como dbt test | Removido | Séries macroeconômicas requerem contexto histórico — concern Gold. |
| `astronomer-cosmos`           | Deferido   | Justificado para 10+ modelos. 3 modelos não requerem essa camada.  |
| Multiple environments (staging/prod) | Simplificado | Apenas `dev` (local) e `airflow` (container) para portfolio. |
| `indice_base100` IPCA         | Removido   | Cálculo cumulativo desde 1994 — concern analítico da Gold layer.   |

---

## Pré-requisitos Bloqueantes

### PRE-01 — `dbt-postgres` no `requirements.txt`

```
dbt-postgres
```

Rebuild da imagem Airflow necessário: `make down && make up PROFILE=orchestration`.

### PRE-02 — `dbt_project.yml` com profile `finlake` e `profiles.yml` configurado

`profiles.yml` deve existir em `transform/profiles.yml` com target `airflow`
apontando para `postgres:5432` — host interno Docker.

### PRE-03 — Bind mount `./transform` no container Airflow

```yaml
# docker/compose.airflow.yml — seção volumes
- ../transform:/opt/airflow/transform
```

Sem este mount, `cwd = '/opt/airflow/transform'` na `BashOperator` não existe
e o `dbt run` falha com `directory not found`.

---

## Requisitos Rascunho para `/define`

### Funcionais

- **RF-01:** Projeto dbt inicializado em `transform/` com `dbt_project.yml`
  e `profiles.yml` (targets: `dev` e `airflow`).
- **RF-02:** Modelos dbt `selic_daily`, `ipca_monthly`, `ptax_daily` em
  `transform/models/domain_bcb/` materializados como `table`.
- **RF-03:** `sources.yml` declarando `bronze_bcb` como fonte dbt.
- **RF-04:** `schema.yml` com `not_null` e `unique` em `date` para todos
  os modelos; nota de comportamento para NULLs esperados em colunas derivadas.
- **RF-05:** Schema `silver_bcb` criado via migration SQL
  `docker/postgres/migrations/002_silver_bcb.sql`.
- **RF-06:** DAG `dag_silver_bcb` com `ExternalTaskSensor` + `BashOperator`.

### Não-Funcionais

- **RNF-01:** Modelos dbt idempotentes — `dbt run` duas vezes no mesmo dia
  produz resultado idêntico (`materialization: table` garante isso).
- **RNF-02:** `profiles.yml` sem credenciais hardcoded — usa `env_var()` do dbt.
- **RNF-03:** `dbt test` deve passar com 0 failures após `dbt run`.

### Pré-requisitos

- **PRE-01:** `dbt-postgres` adicionado ao `requirements.txt`.
- **PRE-02:** `profiles.yml` configurado com targets `dev` e `airflow`.
- **PRE-03:** Bind mount `./transform:/opt/airflow/transform` no `compose.airflow.yml`.

---

## Próximos Passos

```
/define .claude/sdd/features/BRAINSTORM_SILVER_BCB.md
```
