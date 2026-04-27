# DEFINE: Bronze CVM — Ingestão de Fundos de Investimento

> Camada Bronze do domínio CVM: ingestão do cadastro de fundos (`cad_fi.csv`)
> e do informe diário (`inf_diario_fi_YYYYMM.zip`) para o schema `bronze_cvm`
> no PostgreSQL 15, com carga histórica via PySpark e delta incremental via Airflow.

## Metadata

| Atributo          | Valor                                              |
|-------------------|----------------------------------------------------|
| **Feature**       | BRONZE_CVM                                         |
| **Data**          | 2026-04-27                                         |
| **Autor**         | Nilton Coura                                       |
| **Status**        | 🔄 In Progress                                     |
| **Clarity Score** | 14/15                                              |
| **Origem**        | BRAINSTORM_BRONZE_CVM.md (2026-04-27)              |
| **Upstream**      | METABASE_BCB (shipped 2026-04-26)                  |

---

## Problem Statement

O domínio CVM (domain_funds) não possui dados ingeridos: a camada Bronze está
ausente, bloqueando qualquer pipeline downstream — Silver, Gold e análise de
fundos de investimento. O portal de dados abertos da CVM disponibiliza dois
datasets públicos críticos (`cad_fi.csv` e `inf_diario_fi_YYYYMM.zip`) com
histórico desde 2000, mas a stack atual não tem nenhum mecanismo de ingestão.

O desafio técnico central é a **escala assimétrica**: o cadastro tem ~30k
registros diários (trivial), enquanto o informe diário acumula dezenas de
milhões de linhas desde 2005 — exigindo estratégias distintas para carga
histórica (PySpark bulk) e delta incremental (Airflow mensal).

---

## Target Users

| Usuário               | Papel                                  | Pain Point                                                            |
|-----------------------|----------------------------------------|-----------------------------------------------------------------------|
| Nilton Coura          | Data Engineer / dono da plataforma     | Domínio CVM sem dados — nenhum pipeline Silver/Gold pode ser criado   |
| Pipeline Silver_CVM   | Consumidor downstream automatizado     | Depende de `bronze_cvm.informe_diario` populado para transformações   |
| Recrutadores          | Consumidores do portfólio              | CVM demonstra dados financeiros reais e escala (dezenas de M de rows) |

---

## Goals

| Prioridade | Goal                                                                                                  |
|------------|-------------------------------------------------------------------------------------------------------|
| **MUST**   | Schema `bronze_cvm` criado via migration `004_bronze_cvm.sql` com tabelas particionadas              |
| **MUST**   | `cvm_client.py` centraliza download ZIP, descompressão em memória e parse latin1 → UTF-8             |
| **MUST**   | DAG `dag_bronze_cvm_cadastro` operacional: `@daily`, SCD Tipo 1 via `ON CONFLICT DO UPDATE`          |
| **MUST**   | DAG `dag_bronze_cvm_informe` operacional: `@monthly`, `catchup=False`, mês anterior                  |
| **MUST**   | Script PySpark `historical_load_cvm.py` com `--start-year`/`--end-year`, bifurcação HIST/DADOS       |
| **MUST**   | Idempotência: PK `(cnpj_fundo, dt_comptc)` + `ON CONFLICT DO NOTHING` no informe                    |
| **MUST**   | Validação Pydantic para campos críticos (CNPJ, datas, valores numéricos) antes de qualquer insert    |
| **MUST**   | Colunas de auditoria `ingested_at` e `source_url` em todas as tabelas                                |
| **MUST**   | Migration `004_bronze_cvm.sql` executada via `make migrate`                                          |
| **SHOULD** | Testes unitários para `cvm_client.py`, `loaders_cadastro.py`, `loaders_informe.py`                   |
| **SHOULD** | `make` targets: `cvm-migrate`, `cvm-hist-load`, `cvm-cadastro-test`                                  |

---

## Success Criteria

- [ ] `docker exec finlake-postgres psql ... -c "\dn bronze_cvm"` retorna o schema
- [ ] `bronze_cvm.cadastro` existe com ~30k linhas após primeira execução do DAG cadastro
- [ ] `bronze_cvm.informe_diario` existe com partições `_hist`, `_2021`...`_2026`
- [ ] Após `historical_load_cvm.py --start-year 2024 --end-year 2024`, `informe_diario` tem 12 meses de dados
- [ ] Segunda execução do PySpark com mesmo intervalo não duplica registros
- [ ] DAG `dag_bronze_cvm_cadastro` aparece na UI Airflow sem erros de parse
- [ ] DAG `dag_bronze_cvm_informe` aparece na UI Airflow sem erros de parse
- [ ] `ruff check .` — 0 erros
- [ ] `pytest tests/domain_cvm/` — todos passam
- [ ] Encoding latin1 da CVM não gera erros de UnicodeDecodeError no PostgreSQL UTF-8

---

## Acceptance Tests

| ID     | Cenário                                   | Given                                                     | When                                                                 | Then                                                                            |
|--------|-------------------------------------------|-----------------------------------------------------------|----------------------------------------------------------------------|---------------------------------------------------------------------------------|
| AT-001 | Migration cria schema e tabelas           | PostgreSQL sem `bronze_cvm`                               | `make migrate` (ou `004_bronze_cvm.sql` executada)                  | Schema e 2 tabelas criados; partições `_hist`, `_2021`..`_2026` existem         |
| AT-002 | Cadastro: primeira ingestão               | `bronze_cvm.cadastro` vazia                               | DAG `dag_bronze_cvm_cadastro` executa                                | ~30k linhas inseridas com `ingested_at` e `source_url` preenchidos              |
| AT-003 | Cadastro: idempotência                    | `bronze_cvm.cadastro` com 30k linhas do AT-002            | DAG `dag_bronze_cvm_cadastro` executa novamente                      | Contagem permanece ~30k; `updated_at` atualizado para fundos com mudança        |
| AT-004 | Informe: carga PySpark (janela 1 ano)     | `bronze_cvm.informe_diario` vazia (ou com outros anos)    | `python historical_load_cvm.py --start-year 2024 --end-year 2024`   | 12 meses de 2024 carregados via JDBC; sem duplicatas                            |
| AT-005 | Informe: idempotência PySpark             | Dados de 2024 já presentes (AT-004)                       | Mesmo comando PySpark executado novamente                            | Zero linhas novas inseridas — `ON CONFLICT DO NOTHING` absorve tudo             |
| AT-006 | Informe: DAG mensal — mês anterior        | Dados históricos presentes; mês anterior = 2026-03        | DAG `dag_bronze_cvm_informe` executa                                 | ZIP `inf_diario_fi_202603.zip` baixado e inserido em `informe_diario_2026`      |
| AT-007 | Bifurcação URL HIST/DADOS no PySpark      | `--start-year 2019 --end-year 2021`                       | PySpark executa com janela cruzando 2020→2021                        | URL `HIST/inf_diario_fi_2019.zip` e `2020.zip` usadas; `202101.zip` via DADOS/  |
| AT-008 | Encoding latin1 transparente              | CSV da CVM com caracteres especiais (acentos em `ADMIN`)  | Ingestão via Airflow ou PySpark                                      | Nomes com acentos armazenados corretamente no PostgreSQL UTF-8                  |
| AT-009 | Pydantic rejeita CNPJ inválido            | CSV corrompido com `CNPJ_FUNDO = ""` (vazio)              | `cvm_client.py` processa linha                                       | `ValidationError` levantado — linha descartada com log de warning               |

---

## Out of Scope

| Item                                           | Motivo                                                                          |
|------------------------------------------------|---------------------------------------------------------------------------------|
| Silver_CVM (dbt models)                        | Feature seguinte — depende do Bronze estar completo                             |
| Parquet files paralelos ao PostgreSQL          | Deferido — DuckDB lê direto do PostgreSQL no MVP atual                          |
| Great Expectations no Bronze                   | Validação é concern da Silver; Pydantic garante tipos críticos na ingestão      |
| SCD Tipo 2 no Bronze                           | Bronze espelha o estado atual; histórico de mudanças é design da Silver         |
| Particionamento mensal do informe              | Anual é suficiente (~7 partições vs ~250); sem ganho real no contexto local     |
| Tabela `pipeline_runs` de controle             | Airflow persiste execuções nativamente; PySpark usa logging                     |
| Download paralelo de múltiplos ZIPs no Airflow | Paralelismo é responsabilidade do PySpark; Airflow processa 1 ZIP/mês          |
| Informe diário anual pré-2000                  | CVM disponibiliza desde 2000; fora do escopo histórico definido                 |
| Integração com LangFuse / observabilidade AI   | Infra de observabilidade ainda não configurada; não é Bronze                    |

---

## Constraints

| Tipo       | Constraint                                                                                    | Impacto                                                           |
|------------|-----------------------------------------------------------------------------------------------|-------------------------------------------------------------------|
| Técnico    | CVM entrega informe como ZIP (não CSV direto) — descompressão obrigatória em memória          | `zipfile.ZipFile(io.BytesIO(content))` — não salvar em disco      |
| Técnico    | Encoding ISO-8859-1 (latin1) em todos os arquivos CVM — PostgreSQL armazena UTF-8            | Decode explícito antes de qualquer insert                         |
| Técnico    | Dois schemas de URL distintos: `HIST/inf_diario_fi_{YYYY}.zip` (≤2020) vs `DADOS/YYYYMM.zip` | Lógica de bifurcação obrigatória em `cvm_client.py` e PySpark     |
| Técnico    | `ON CONFLICT` em tabela particionada requer que a PK inclua a coluna de partição              | PK de `informe_diario` é `(cnpj_fundo, dt_comptc)` — dt_comptc é a coluna de partição |
| Infra      | PySpark JDBC requer JAR `postgresql-42.x.jar` disponível no classpath                        | Configurar `spark.jars` antes de executar o job histórico         |
| Portfólio  | Script PySpark deve rodar localmente com Spark standalone (não cluster)                       | `master("local[*]")` — sem YARN/K8s                               |
| Segurança  | JDBC URL do PostgreSQL nunca hardcoded — via variável de ambiente                             | `os.environ["FINLAKE_JDBC_URL"]` obrigatório no script PySpark    |

---

## Technical Context

| Aspecto                   | Valor                                               | Notas                                        |
|---------------------------|-----------------------------------------------------|----------------------------------------------|
| **Cadastro URL**          | `https://dados.cvm.gov.br/dados/FI/CAD/DADOS/cad_fi.csv` | Arquivo único, atualizado diariamente     |
| **Informe URL (recente)** | `DADOS/inf_diario_fi_{YYYYMM}.zip`                  | A partir de 2021                             |
| **Informe URL (hist)**    | `DADOS/HIST/inf_diario_fi_{YYYY}.zip`               | De 2000 a 2020 — arquivo anual               |
| **Separador CSV**         | `;` (ponto e vírgula)                               | Ambos os arquivos                            |
| **Encoding**              | ISO-8859-1 (latin1)                                 | Decode para UTF-8 antes do insert            |
| **Coluna extra informe**  | `TP_FUNDO` — não documentada, mas presente          | Incluída na tabela e nos modelos Pydantic    |
| **Schema PostgreSQL**     | `bronze_cvm`                                        | Isolado de `bronze_bcb` (Data Mesh)          |
| **Connection Airflow**    | `AIRFLOW_CONN_FINLAKE_POSTGRES`                     | Já configurada no domínio BCB — reutilizar   |
| **PySpark mode**          | `local[*]` — Spark standalone                       | Sem cluster; job executado fora do Airflow   |
| **JDBC JAR**              | `postgresql-42.x.jar`                               | Necessário para Spark → PostgreSQL via JDBC  |

---

## Data Contracts

### Fonte: `cad_fi.csv` → `bronze_cvm.cadastro`

| Coluna CSV     | Coluna PostgreSQL  | Tipo SQL        | Nullable |
|----------------|--------------------|-----------------|----------|
| `CNPJ_FUNDO`   | `cnpj_fundo`       | `VARCHAR(18)`   | NOT NULL (PK) |
| `TP_FUNDO`     | `tp_fundo`         | `VARCHAR(100)`  | YES      |
| `DENOM_SOCIAL` | `denom_social`     | `VARCHAR(200)`  | YES      |
| `DT_REG`       | `dt_reg`           | `DATE`          | YES      |
| `DT_CONST`     | `dt_const`         | `DATE`          | YES      |
| `CD_CVM`       | `cd_cvm`           | `VARCHAR(20)`   | YES      |
| `DT_CANCEL`    | `dt_cancel`        | `DATE`          | YES      |
| `SIT`          | `sit`              | `VARCHAR(80)`   | YES      |
| `DT_INI_SIT`   | `dt_ini_sit`       | `DATE`          | YES      |
| `DT_INI_ATIV`  | `dt_ini_ativ`      | `DATE`          | YES      |
| `CLASSE`       | `classe`           | `VARCHAR(100)`  | YES      |
| `RENTAB_FUNDO` | `rentab_fundo`     | `VARCHAR(200)`  | YES      |
| `TAXA_PERFM`   | `taxa_perfm`       | `NUMERIC(10,4)` | YES      |
| `TAXA_ADM`     | `taxa_adm`         | `NUMERIC(10,4)` | YES      |
| `VL_PATRIM_LIQ`| `vl_patrim_liq`    | `NUMERIC(18,6)` | YES      |
| `CNPJ_ADMIN`   | `cnpj_admin`       | `VARCHAR(18)`   | YES      |
| `ADMIN`        | `admin`            | `VARCHAR(200)`  | YES      |
| `CNPJ_GESTOR`  | `cnpj_gestor`      | `VARCHAR(18)`   | YES      |
| `GESTOR`       | `gestor`           | `VARCHAR(200)`  | YES      |
| `CNPJ_AUDITOR` | `cnpj_auditor`     | `VARCHAR(18)`   | YES      |
| `AUDITOR`      | `auditor`          | `VARCHAR(200)`  | YES      |
| `CLASSE_ANBIMA`| `classe_anbima`    | `VARCHAR(100)`  | YES      |
| *(auditoria)*  | `ingested_at`      | `TIMESTAMP`     | NOT NULL DEFAULT NOW() |
| *(auditoria)*  | `updated_at`       | `TIMESTAMP`     | NOT NULL DEFAULT NOW() |
| *(auditoria)*  | `source_url`       | `VARCHAR(300)`  | NOT NULL |

### Fonte: `inf_diario_fi_YYYYMM.zip` → `bronze_cvm.informe_diario`

| Coluna CSV      | Coluna PostgreSQL | Tipo SQL         | Nullable |
|-----------------|-------------------|------------------|----------|
| `TP_FUNDO`      | `tp_fundo`        | `VARCHAR(10)`    | YES      |
| `CNPJ_FUNDO`    | `cnpj_fundo`      | `VARCHAR(18)`    | NOT NULL (PK) |
| `DT_COMPTC`     | `dt_comptc`       | `DATE`           | NOT NULL (PK + partição) |
| `VL_TOTAL`      | `vl_total`        | `NUMERIC(18,6)`  | YES      |
| `VL_QUOTA`      | `vl_quota`        | `NUMERIC(18,8)`  | YES      |
| `VL_PATRIM_LIQ` | `vl_patrim_liq`   | `NUMERIC(18,6)`  | YES      |
| `CAPTC_DIA`     | `captc_dia`       | `NUMERIC(18,6)`  | YES      |
| `RESG_DIA`      | `resg_dia`        | `NUMERIC(18,6)`  | YES      |
| `NR_COTST`      | `nr_cotst`        | `INTEGER`        | YES      |
| *(auditoria)*   | `ingested_at`     | `TIMESTAMP`      | NOT NULL DEFAULT NOW() |
| *(auditoria)*   | `source_url`      | `VARCHAR(300)`   | NOT NULL |

---

## Pré-requisitos Bloqueantes

### PRE-01 — Dependências Python no container Airflow

```txt
requests>=2.31
pandas>=2.0
pydantic>=2.0
apache-airflow-providers-postgres   # já presente — reutilizar
```

### PRE-02 — PySpark com JDBC driver PostgreSQL

```
spark.jars = /path/to/postgresql-42.x.jar
```

Ou via `spark-submit --jars postgresql-42.x.jar`.

### PRE-03 — Variável de ambiente para JDBC no PySpark

```bash
export FINLAKE_JDBC_URL="jdbc:postgresql://localhost:5433/finlake"
export FINLAKE_JDBC_USER="postgres"
export FINLAKE_JDBC_PASSWORD="supabase123"
```

### PRE-04 — Migration executada antes do primeiro deploy

```bash
make migrate   # executa 004_bronze_cvm.sql após os demais
```

### PRE-05 — `AIRFLOW_CONN_FINLAKE_POSTGRES` (já configurada no BCB)

---

## Assumptions

| ID    | Assumption                                                               | Se errada, impacto                                                     | Validado? |
|-------|--------------------------------------------------------------------------|------------------------------------------------------------------------|-----------|
| A-001 | URLs `HIST/` e `DADOS/` permanecem estáveis — CVM não altera a estrutura | Script quebra silenciosamente — validar com `HEAD` request antes de download | [ ] |
| A-002 | `TP_FUNDO` está presente em todos os arquivos de informe                 | Parse falha — coluna extra não documentada pode desaparecer em novos meses | [ ] |
| A-003 | `ON CONFLICT` funciona em tabela particionada com PK `(cnpj_fundo, dt_comptc)` | Insert falha — PostgreSQL 15 suporta, mas precisa validar na migration | [ ] |
| A-004 | Encoding ISO-8859-1 é consistente em todos os arquivos CVM (histórico)   | UnicodeDecodeError em meses antigos — usar `errors='replace'` como fallback | [ ] |
| A-005 | CSV do cadastro sempre tem header na linha 1                             | Parse incorreto — validar com amostra de 2 linhas no AT antes de inserir | [ ] |

---

## Clarity Score Breakdown

| Elemento | Score | Justificativa                                                                 |
|----------|-------|-------------------------------------------------------------------------------|
| Problem  | 3/3   | Domínio CVM sem dados + desafio de escala assimétrica — específico e concreto |
| Users    | 2/3   | Nilton e pipeline downstream explícitos; recrutadores como secundários        |
| Goals    | 3/3   | MUST/SHOULD priorizados; PySpark + Airflow com responsabilidades separadas    |
| Success  | 3/3   | ATs testáveis com comandos SQL exatos e contagens verificáveis               |
| Scope    | 3/3   | 9 itens explicitamente fora do escopo; limites documentados                   |
| **Total**| **14/15** |                                                                           |

**Mínimo para prosseguir: 12/15 ✅**

---

## Open Questions

Nenhuma — todas as decisões arquiteturais foram resolvidas no Brainstorm.

A-001 a A-005 devem ser validadas no início do Build:
- A-003 é crítica: criar tabela de teste com partição + `ON CONFLICT` antes de escrever código.

---

## Revision History

| Versão | Data       | Autor        | Mudanças                                                         |
|--------|------------|--------------|------------------------------------------------------------------|
| 1.0    | 2026-04-27 | define-agent | Versão inicial from BRAINSTORM_BRONZE_CVM.md — all decisions pre-validated |

---

## Next Step

**Pronto para:** `/design .claude/sdd/features/DEFINE_BRONZE_CVM.md`
