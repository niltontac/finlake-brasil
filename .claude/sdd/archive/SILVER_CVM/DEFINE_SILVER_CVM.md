# DEFINE: Silver CVM — Transformação e Validação do Domínio Fundos

> Transformar `bronze_cvm.cadastro` e `bronze_cvm.informe_diario` em modelos Silver validados, tipados e prontos para o Gold CVM calcular rentabilidade, PL médio e captação líquida de fundos ativos.

## Metadata

| Atributo | Valor |
|----------|-------|
| **Feature** | SILVER_CVM |
| **Data** | 2026-04-29 |
| **Autor** | define-agent |
| **Status** | Shipped |
| **Clarity Score** | 15/15 |
| **Origem** | BRAINSTORM_SILVER_CVM.md (2026-04-28) |

---

## Problem Statement

O domínio `domain_funds` tem dados brutos completos no Bronze (41k fundos no cadastro, 6,5M registros de informe em 2024), mas sem transformação, tipagem ou validação que permita ao Gold calcular métricas financeiras confiáveis. Os dois modelos Bronze foram ingeridos propositalmente sem JOIN entre si — a Silver CVM é a camada responsável por filtrar fundos operacionais, tipar corretamente os valores financeiros, derivar `captacao_liquida`, e entregar dois modelos limpos que o Gold componha com flexibilidade.

---

## Target Users

| Usuário | Papel | Necessidade |
|---------|-------|-------------|
| Gold CVM (modelos dbt futuros) | Consumidor downstream | `fundos` e `informe_diario` limpos e tipados para JOIN e agregação — sem depender do Bronze |
| Analista de dados (Metabase) | Consumidor analítico | Visão de fundos ativos com série temporal válida e `captacao_liquida` já calculada |

---

## Goals

O que sucesso significa, em ordem de prioridade:

| Prioridade | Goal |
|------------|------|
| **MUST** | `silver_cvm.fundos` materializado como `table` com fundos `sit IN ('EM FUNCIONAMENTO NORMAL', 'EM LIQUIDAÇÃO')` — ~2.500 rows |
| **MUST** | `silver_cvm.informe_diario` materializado como `incremental` com janela de 30 dias e `delete+insert` |
| **MUST** | Coluna derivada `captacao_liquida = captc_dia - resg_dia` presente em `silver_cvm.informe_diario` |
| **MUST** | `dbt test` passa com zero erros (warnings de FK são aceitos — `severity: warn`) |
| **MUST** | `dag_silver_cvm` executa com sucesso no Airflow, aguardando `dag_bronze_cvm_cadastro` via `ExternalTaskSensor` |
| **SHOULD** | `publico_alvo` incluído em `silver_cvm.fundos` para segmentação Gold (fundos exclusivos vs abertos) |
| **SHOULD** | `fundo_exclusivo` incluído em `silver_cvm.fundos` (flag `S`/`N`) |
| **SHOULD** | Testes dbt documentados em `schema.yml`: `not_null`, `unique`, `accepted_values`, `relationships` |
| **COULD** | `dbt source freshness` configurado para `bronze_cvm` com warn/error após SLAs definidos |

**Nota sobre `publico_alvo`:** Campo presente na fonte, removido inicialmente por YAGNI, mas confirmado como SHOULD durante validação do brainstorm. Útil para segmentar fundos exclusivos vs abertos no Gold sem precisar de JOIN adicional ou retrocompatibilidade. Incluído explicitamente neste DEFINE para eliminar a ambiguidade do brainstorm.

---

## Success Criteria

Resultados mensuráveis que definem "done":

- [ ] `silver_cvm.fundos` contém entre 1.500 e 5.000 rows após `dbt run` (filtro de situação aplicado sobre 41k do Bronze)
- [ ] `silver_cvm.informe_diario` contém todos os registros históricos do Bronze + novos registros em runs subsequentes, sem duplicatas
- [ ] `dbt test --select domain_cvm` retorna zero failures (warnings de FK são aceitos)
- [ ] `captacao_liquida` é não-nula em ≥ 90% dos registros onde `captc_dia` e `resg_dia` são ambos não-nulos
- [ ] `dag_silver_cvm` completa com status `success` na UI do Airflow após `dag_bronze_cvm_cadastro` concluir
- [ ] `silver_cvm.fundos.publico_alvo` presente como coluna com valores não-nulos para fundos com público alvo definido na fonte
- [ ] Migration `005_silver_cvm.sql` idempotente: executar duas vezes não gera erros

---

## Acceptance Tests

| ID | Cenário | Given | When | Then |
|----|---------|-------|------|------|
| AT-001 | Filtro de situação no model `fundos` | `bronze_cvm.cadastro` com 41k fundos, maioria `sit = 'CANCELADA'` | `dbt run --select fundos` | `silver_cvm.fundos` contém apenas fundos com `sit IN ('EM FUNCIONAMENTO NORMAL', 'EM LIQUIDAÇÃO')` |
| AT-002 | Materialização incremental do informe | `silver_cvm.informe_diario` populado; Bronze tem novos registros do último mês | `dbt run --select informe_diario` | Apenas registros com `dt_comptc >= MAX(dt_comptc) - 30 dias` processados; zero duplicatas |
| AT-003 | Coluna `captacao_liquida` derivada | Registros em Bronze com `captc_dia = 1000.00` e `resg_dia = 600.00` | `dbt run --select informe_diario` | `captacao_liquida = 400.00` para esse registro; NULL onde ambos os campos-base são NULL |
| AT-004 | FK warning sem bloqueio de pipeline | Registros em `bronze_cvm.informe_diario` com `cnpj_fundo` sem match em `silver_cvm.fundos` (fundos cancelados) | `dbt test --select informe_diario` | Pipeline não falha; log contém warning de `relationships`; exit code 0 |
| AT-005 | DAG com ExternalTaskSensor | `dag_bronze_cvm_cadastro` concluída com status `success` no dia corrente | `dag_silver_cvm` trigger diário | `wait_bronze_cvm_cadastro` detecta conclusão; `dbt_run_silver_cvm` executa em seguida |
| AT-006 | Idempotência do model `fundos` | `silver_cvm.fundos` já existente com dados | `dbt run --select fundos` executado pela segunda vez | Tabela recriada com mesmo conteúdo; zero erros; contagem de rows idêntica |
| AT-007 | `publico_alvo` presente no Silver | `bronze_cvm.cadastro` com valores distintos em `publico_alvo` | `dbt run --select fundos` | `silver_cvm.fundos` tem coluna `publico_alvo`; valores não-nulos para fundos com público alvo definido |
| AT-008 | Schema override `silver_cvm` | `profiles.yml` com `schema: silver_bcb` como default | `dbt run --select domain_cvm` | Modelos materializados em `silver_cvm.*`, não em `silver_bcb.*` |
| AT-009 | Migration idempotente | `005_silver_cvm.sql` já executada | Executar `005_silver_cvm.sql` pela segunda vez | Zero erros; schema `silver_cvm` intacto |

---

## Out of Scope

Explicitamente **não incluído** nesta feature:

- **SCD Tipo 2** para histórico de situação do fundo — dbt snapshots fora do MVP; valor analítico do domínio está na série temporal do informe, não no histórico de atributos do cadastro
- **Modelo enriquecido na Silver** (JOIN cadastro+informe) — JOIN pertence ao Gold, que tem flexibilidade para compor conforme seus contratos analíticos
- **dbt snapshots** de qualquer entidade
- **Staging intermediário** (`stg_cvm_*`) — casting direto no model é suficiente para esta escala
- **23 colunas do cadastro Bronze não usadas pelo Gold MVP**: `inf_taxa_perfm`, `inf_taxa_adm`, CNPJs de terceiros (`cnpj_admin`, `cnpj_custodiante`, `cnpj_controlador`, `cnpj_auditor`, `cpf_cnpj_gestor`), `diretor`, `auditor`, `custodiante`, `controlador`, `rentab_fundo`, `condom`, `trib_lprazo`, `entid_invest`, `invest_cempr_exter`, `vl_patrim_liq` (cadastro), `dt_patrim_liq`, `dt_ini_exerc`, `dt_fim_exerc`, `dt_cancel`, `cd_cvm` — podem ser adicionadas individualmente quando o Gold precisar
- **DAG separada para informe mensal** — overhead operacional desnecessário; incremental é no-op nos dias sem novos dados do Bronze
- **Dados históricos pré-2024** como requisito — Bronze tem, Silver herda naturalmente via primeira carga incremental (full load na ausência de registros prévios)

---

## Constraints

| Tipo | Restrição | Impacto |
|------|-----------|---------|
| Técnico | `profiles.yml` tem `schema: silver_bcb` como default de `target: dev` e `target: airflow` | `dbt_project.yml` deve ter `+schema: silver_cvm` explícito no bloco `domain_cvm`; sem isso, modelos iriam para `silver_bcb` |
| Técnico | `incremental_strategy: 'delete+insert'` — único suportado pelo dbt-postgres (não `merge`) | Sem merge nativo; `delete+insert` é atômico por `unique_key` — comportamento correto para este caso |
| Técnico | PostgreSQL 15 com particionamento nativo em `bronze_cvm.informe_diario` | `source()` dbt aponta para a tabela pai `informe_diario`; PostgreSQL roteia automaticamente para a partição correta — sem necessidade de referenciar partições individualmente |
| Técnico | dbt não cria schemas automaticamente — PostgreSQL requer DDL explícita | Migration `005_silver_cvm.sql` com `CREATE SCHEMA IF NOT EXISTS silver_cvm` deve existir antes do `dbt run` |
| Operacional | `dag_bronze_cvm_informe` é `@monthly` (não `@daily`) | Silver DAG aguarda apenas `dag_bronze_cvm_cadastro` (daily); incremental do informe é no-op nos dias sem novos dados Bronze — correto por design |
| Operacional | Volume da janela incremental: ~540k registros/run (30 dias × ~18k/dia) | Dentro das capacidades do PostgreSQL local; sem necessidade de otimização adicional para o MVP |

---

## Technical Context

| Aspecto | Valor | Notas |
|---------|-------|-------|
| **Localização dbt models** | `transform/models/domain_cvm/` | Novo diretório, mesmo padrão de `transform/models/domain_bcb/` |
| **Schema destino** | `silver_cvm` | Override via `+schema: silver_cvm` em `dbt_project.yml` no bloco `domain_cvm` |
| **DAG location** | `dags/domain_funds/` | Consistente com `dags/domain_bcb/`; cria `dag_silver_cvm.py` nesse diretório |
| **Migration** | `docker/postgres/migrations/005_silver_cvm.sql` | Numeração sequencial após `004_bronze_cvm.sql` |
| **Padrão de referência** | `transform/models/domain_bcb/` + `dags/domain_bcb/dag_silver_bcb.py` | Replicar estrutura de `sources.yml`, `schema.yml`, modelos SQL e DAG |
| **IaC Impact** | Modificar `Makefile` target `migrate` + `dbt_project.yml` | Adicionar `005_silver_cvm.sql` ao target `migrate`; adicionar bloco `domain_cvm` no `dbt_project.yml` |

---

## Data Contract

### Source Inventory

| Fonte | Tipo | Volume | Freshness | Owner |
|-------|------|--------|-----------|-------|
| `bronze_cvm.cadastro` | PostgreSQL table (SCD1) | 41.107 fundos | Diário (dag_bronze_cvm_cadastro) | domain_funds |
| `bronze_cvm.informe_diario` | PostgreSQL partitioned table | 6,5M+ registros (2024) | Mensal (dag_bronze_cvm_informe) | domain_funds |

### Schema Contract — `silver_cvm.fundos`

| Coluna | Tipo | Restrições | PII? |
|--------|------|------------|------|
| `cnpj_fundo` | `VARCHAR(18)` | `NOT NULL`, `UNIQUE` | Não |
| `tp_fundo` | `VARCHAR(100)` | `NOT NULL` | Não |
| `denom_social` | `TEXT` | `NOT NULL` | Não |
| `sit` | `VARCHAR(80)` | `NOT NULL`, `IN ('EM FUNCIONAMENTO NORMAL', 'EM LIQUIDAÇÃO')` | Não |
| `classe` | `VARCHAR(100)` | — | Não |
| `classe_anbima` | `VARCHAR(100)` | — | Não |
| `publico_alvo` | `TEXT` | — | Não |
| `fundo_exclusivo` | `VARCHAR(1)` | `IN ('S', 'N')` | Não |
| `taxa_adm` | `NUMERIC(10,4)` | — | Não |
| `taxa_perfm` | `NUMERIC(10,4)` | — | Não |
| `dt_ini_ativ` | `DATE` | — | Não |
| `dt_fim_ativ` | `DATE` | — | Não |
| `admin` | `TEXT` | — | Não |
| `gestor` | `TEXT` | — | Não |
| `transformed_at` | `TIMESTAMP` | `NOT NULL` | Não |

### Schema Contract — `silver_cvm.informe_diario`

| Coluna | Tipo | Restrições | PII? |
|--------|------|------------|------|
| `cnpj_fundo` | `VARCHAR(18)` | `NOT NULL` | Não |
| `dt_comptc` | `DATE` | `NOT NULL` | Não |
| `tp_fundo` | `VARCHAR(50)` | — | Não |
| `vl_total` | `NUMERIC(22,6)` | — | Não |
| `vl_quota` | `NUMERIC(22,8)` | — | Não |
| `vl_patrim_liq` | `NUMERIC(22,6)` | — | Não |
| `captc_dia` | `NUMERIC(22,6)` | — | Não |
| `resg_dia` | `NUMERIC(22,6)` | — | Não |
| `captacao_liquida` | `NUMERIC(22,6)` | Derivada: `captc_dia - resg_dia` | Não |
| `nr_cotst` | `INTEGER` | — | Não |
| `transformed_at` | `TIMESTAMP` | `NOT NULL` | Não |

### Freshness SLAs

| Camada | Target | Medição |
|--------|--------|---------|
| `silver_cvm.fundos` | Atualizado até 02:00 UTC diariamente | Conclusão de `dag_silver_cvm` |
| `silver_cvm.informe_diario` | Atualizado até 02:00 UTC diariamente (no-op quando sem novos dados) | Conclusão de `dag_silver_cvm` |

### Completeness Metrics

- `silver_cvm.fundos`: zero registros com `cnpj_fundo` nulo; zero duplicatas de CNPJ
- `silver_cvm.informe_diario`: zero registros com `(cnpj_fundo, dt_comptc)` duplicados; `captacao_liquida` nula apenas quando `captc_dia` ou `resg_dia` forem nulos

### Lineage Requirements

- `silver_cvm.fundos` ← `bronze_cvm.cadastro` (filtragem + tipagem)
- `silver_cvm.informe_diario` ← `bronze_cvm.informe_diario` (tipagem + derivação + janela incremental)
- `gold_cvm.*` ← `ref('fundos')` JOIN `ref('informe_diario')` (composição no Gold)

---

## Assumptions

| ID | Assumption | Se Errado, Impacto | Validado? |
|----|------------|-------------------|-----------|
| A-001 | `+schema: silver_cvm` no bloco `domain_cvm` do `dbt_project.yml` sobrescreve o default `silver_bcb` sem afetar `domain_bcb` | Modelos CVM materializariam no schema errado | [ ] Validar com `dbt compile --select domain_cvm` |
| A-002 | `incremental_strategy: 'delete+insert'` está disponível na versão de `dbt-postgres` instalada no container | Fallback necessário para `append` + deduplicação manual | [ ] Validar com `dbt run --select informe_diario` no primeiro run |
| A-003 | `source()` dbt apontando para `bronze_cvm.informe_diario` (tabela pai) retorna dados corretamente via PostgreSQL partition routing | Precisaria de `source()` por partição ou UNION nos modelos | [ ] Validar com `dbt source freshness` ou query direta |
| A-004 | O volume incremental de ~540k registros/run é executado dentro do timeout padrão do Airflow (`dagrun_timeout=None`) | Precisaria de `dagrun_timeout` explícito na DAG | [ ] Monitorar duration no primeiro run completo |
| A-005 | A coluna `sit` em `bronze_cvm.cadastro` tem valores limpos: sem espaços extras, encoding correto (latin1→UTF8 já tratado na ingestão) | `accepted_values` test falharia por variações de whitespace | [ ] Validar com `SELECT DISTINCT sit FROM bronze_cvm.cadastro` |
| A-006 | `captc_dia` e `resg_dia` nunca são negativos — apenas zeros ou positivos | `captacao_liquida` poderia indicar erro de dado em vez de resgate líquido | [ ] Validar com `SELECT MIN(captc_dia), MIN(resg_dia) FROM bronze_cvm.informe_diario` |

---

## Clarity Score Breakdown

| Elemento | Score (0-3) | Notas |
|----------|-------------|-------|
| Problem | 3 | Problema específico, causa raiz clara, impacto mensurável (Gold não pode computar sem Silver) |
| Users | 3 | Dois usuários identificados com necessidades distintas: Gold (modelo dbt) + Analista (Metabase) |
| Goals | 3 | 5 MUSTs mensuráveis + 3 SHOULDs com critérios claros; `publico_alvo` com justificativa explícita |
| Success | 3 | 7 critérios testáveis com números (1.500-5.000 rows, ≥90% captacao_liquida, zero failures) |
| Scope | 3 | Out-of-scope explícito com 23 colunas nomeadas, decisões de exclusão documentadas com rationale |
| **Total** | **15/15** | Pronto para Design |

---

## Open Questions

Nenhuma — pronto para Design.

As assumptions A-001 a A-006 são validações de infraestrutura a confirmar durante o Build (via smoke tests), não bloqueadores do Design.

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-29 | define-agent | Versão inicial a partir de BRAINSTORM_SILVER_CVM.md |
| 1.0 | 2026-04-29 | define-agent | `publico_alvo` resolvido: incluído como SHOULD (contradição brainstorm eliminada) |

---

## Next Step

**Pronto para:** `/design .claude/sdd/features/DEFINE_SILVER_CVM.md`
