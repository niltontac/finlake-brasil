# BRAINSTORM: Silver CVM — Transformação e Validação do Domínio Fundos

> Sessão exploratória antes da captura formal de requisitos

## Metadata

| Atributo | Valor |
|----------|-------|
| **Feature** | SILVER_CVM |
| **Data** | 2026-04-28 |
| **Autor** | brainstorm-agent |
| **Status** | Pronto para /define |

---

## Ideia Inicial

**Input:** Silver CVM — transformação do Bronze CVM (cadastro + informe_diario) para a camada Silver do domínio `domain_funds`. Base para o Gold calcular rentabilidade, PL médio e captação líquida.

**Contexto observado:**

- Bronze CVM entregue: `bronze_cvm.cadastro` (41.107 fundos, SCD1) + `bronze_cvm.informe_diario` (6,5M registros 2024, particionado por ano)
- Projeto dbt `finlake` já existe em `transform/` com `domain_bcb` (Silver + Gold)
- Padrão Silver BCB estabelecido: `materialized: table`, modelos limpos por série, Gold compõe
- Bronze não fez o JOIN cadastro↔informe propositalmente — decisão arquitetural a resolver na Silver
- `dbt_project.yml` usa `schema: silver_bcb` no `profiles.yml` como default; Gold BCB usa `+schema: gold_bcb` override
- DAG Silver BCB usa `ExternalTaskSensor` + `BashOperator` — padrão a seguir
- Migrations numeradas sequencialmente: próxima será `005_silver_cvm.sql`

**Contexto Técnico:**

| Aspecto | Observação | Implicação |
|---------|------------|------------|
| Localização | `transform/models/domain_cvm/` | Novo diretório, mesmo padrão do `domain_bcb` |
| DAG owner | `domain_funds` / `dags/domain_funds/` | Consistente com `dags/domain_bcb/` |
| Bronze disponível | `bronze_cvm.cadastro` + `bronze_cvm.informe_diario` | Ambos como `source()` dbt |
| Volume crítico | 6,5M registros no informe (2024), ~18k/dia | Exige estratégia incremental |
| Upstream DAG | `dag_bronze_cvm_cadastro` (daily) | ExternalTaskSensor target |

---

## Perguntas de Descoberta

| # | Pergunta | Resposta | Impacto |
|---|----------|---------|---------|
| 1 | O que é "fundo ativo" para a Silver? | `sit IN ('EM FUNCIONAMENTO NORMAL', 'EM LIQUIDAÇÃO')` — critério: "tem dados no informe" | Define o universo de toda a cadeia Silver→Gold→Metabase (~2.500 fundos dos 41k) |
| 2 | SCD Tipo 2 para histórico de situação? | Não. Silver reflete estado atual filtrado. dbt snapshots fora do escopo MVP. | Sem `snapshots/`, sem `valid_from`/`valid_to`. Menor complexidade. |
| 3 | informe_diario: incremental ou full refresh? | Incremental com janela de 30 dias, `delete+insert`, `unique_key: ['cnpj_fundo', 'dt_comptc']` | Custo fixo ~540k rows/run independente do histórico acumulado |
| 4 | JOIN cadastro+informe na Silver ou no Gold? | Modelos separados. Gold faz JOIN com `ref()`. Mesmo padrão Silver BCB. | 2 modelos dbt (não 3). Silver limpa, Gold compõe. |
| 5 | Fundos no informe sem match no cadastro Silver? | Teste `relationships` com `severity: warn`. Silver sinaliza, não bloqueia. | `dbt test` reporta anomalia; INNER vs LEFT JOIN é decisão do Gold |

---

## Inventário de Dados de Referência

| Tipo | Localização | Volume | Notas |
|------|-------------|--------|-------|
| Fonte Bronze cadastro | `bronze_cvm.cadastro` | 41.107 fundos | SCD1, 40 colunas, maioria `sit = 'CANCELADA'` |
| Fonte Bronze informe | `bronze_cvm.informe_diario` | 6,5M registros (2024) | Particionado por ano, chave: `(cnpj_fundo, dt_comptc)` |
| Universo Silver esperado | ~2.500 fundos ativos | filtro `sit IN (...)` | `EM FUNCIONAMENTO NORMAL` + `EM LIQUIDAÇÃO` |
| Padrão de referência | `transform/models/domain_bcb/` | 3 modelos Silver | Padrão SQL, testes dbt, DAG Airflow |

---

## Abordagens Exploradas

### Pergunta 1 — Filtro de fundos ativos

#### Abordagem B: Operacional amplo ⭐ Escolhida
`sit IN ('EM FUNCIONAMENTO NORMAL', 'EM LIQUIDAÇÃO')`

**Rationale:** Fundos em liquidação continuam reportando no informe por meses/anos. Excluí-los criaria um gap: registros existem no informe Silver mas o cadastro Silver não os conhece. O critério semântico é "tem dados no informe", não "está operacional no sentido estrito".

**Rejeitadas:**
- **(a) Só EM FUNCIONAMENTO NORMAL** — excluiria fundos que ainda reportam, causando gap no JOIN Gold
- **(c) Inclui FASE PRÉ-OPERACIONAL** — fundos pré-operacionais não aparecem no informe; dado desnecessário
- **(d) Sem filtro** — transfere responsabilidade de limpeza para o Gold; viola propósito da Silver

---

### Pergunta 2 — SCD Tipo 2

#### Abordagem A: Sem SCD Tipo 2 ⭐ Escolhida
Silver de cadastro reflete estado atual.

**Rationale:** O valor analítico do domínio CVM vem da série temporal do informe (PL, captação, cotas), não do histórico de atributos do cadastro. dbt snapshots adicionam novo tipo de artefato, estratégia `check`/`timestamp` e volume extra — complexidade não justificada para este MVP.

**Rejeitada:**
- **(b) dbt snapshots com valid_from/valid_to** — útil para "qual era o gestor em março/22?", mas o Gold não precisa disso no MVP

---

### Pergunta 3 — Estratégia de materialização do informe

#### Abordagem C: Incremental com janela de 30 dias ⭐ Escolhida

```sql
{% if is_incremental() %}
WHERE dt_comptc >= (
    SELECT MAX(dt_comptc) - INTERVAL '30 days'
    FROM {{ this }}
)
{% endif %}
```

`unique_key: ['cnpj_fundo', 'dt_comptc']`, `incremental_strategy: 'delete+insert'`

**Rationale:** Custo fixo de ~540k registros/run (30 dias × 18k/dia) independente do histórico acumulado. Cobre correções retroativas que a CVM ocasionalmente publica. Equilibra eficiência e robustez.

**Rejeitadas:**
- **(a) materialized: table** — full refresh de 6,5M+ registros diariamente; viável hoje, degrada conforme histórico cresce
- **(b) Incremental puro (sem janela)** — eficiente, mas não captura correções retroativas da CVM

---

### Pergunta 4 — JOIN na Silver ou no Gold

#### Abordagem A: Modelos separados ⭐ Escolhida
`silver_cvm.fundos` + `silver_cvm.informe_diario` independentes.

**Rationale:** Silver limpa cada fonte de forma independente. Gold constrói o que precisa com `ref()`. Mesmo padrão do BCB (Silver limpa séries individuais, Gold faz `macro_diario` unindo SELIC+IPCA+PTAX). Flexibilidade: diferentes modelos Gold podem fazer JOIN diferentes (ex: análise por gestor vs análise por classe ANBIMA).

**Rejeitadas:**
- **(b) Modelo enriquecido Silver** — JOIN de 6,5M rows × atributos cadastro a cada run; repete trabalho desnecessariamente
- **(c) Sem Silver de cadastro** — acoplamento direto Bronze→Gold; Bronze vaza para o Gold

---

### Pergunta 5 — Orphaned records (informe sem cadastro)

#### Abordagem A: `severity: warn` ⭐ Escolhida

```yaml
- name: cnpj_fundo
  tests:
    - relationships:
        to: ref('fundos')
        field: cnpj_fundo
        severity: warn
```

**Rationale:** Silver sinaliza a anomalia sem bloquear o pipeline. Dado histórico válido é preservado. A decisão de `INNER JOIN` vs `LEFT JOIN` pertence ao Gold conforme seu contrato analítico.

**Rejeitadas:**
- **(b) Filtro na Silver** — descartaria dados históricos válidos silenciosamente
- **(c) Sem teste** — perde a sinalização; anomalia passaria despercebida no Airflow

---

## Abordagem Selecionada

| Atributo | Valor |
|----------|-------|
| **Modelos dbt** | 2: `fundos` (table) + `informe_diario` (incremental) |
| **Schema destino** | `silver_cvm` |
| **Filtro cadastro** | `sit IN ('EM FUNCIONAMENTO NORMAL', 'EM LIQUIDAÇÃO')` |
| **Materialização fundos** | `table` (idempotente, ~2.500 rows) |
| **Materialização informe** | `incremental`, janela 30 dias, `delete+insert` |
| **Coluna derivada** | `captacao_liquida = captc_dia - resg_dia` |
| **FK integrity** | `relationships` test com `severity: warn` |
| **DAG pattern** | `ExternalTaskSensor(dag_bronze_cvm_cadastro)` + `BashOperator(dbt run)` |
| **Confirmação do usuário** | 2026-04-28 |

---

## Contexto de Engenharia de Dados

### Fontes
| Fonte | Tipo | Volume | Frequência |
|-------|------|--------|------------|
| `bronze_cvm.cadastro` | PostgreSQL table (SCD1) | 41.107 fundos | Diário |
| `bronze_cvm.informe_diario` | PostgreSQL partitioned table | 6,5M registros (2024) | Mensal |

### Fluxo de Dados

```
bronze_cvm.cadastro              bronze_cvm.informe_diario
     │  (SCD1, diário)                │  (particionado, mensal)
     │                                │
     ▼                                ▼
silver_cvm.fundos              silver_cvm.informe_diario
  materialized: table            materialized: incremental
  ~2.500 rows                    ~6,5M+ rows (janela 30d/run)
  dbt run: segundos              dbt run: ~540k rows
     │                                │
     └────────────────────────────────┘
                  ▼
          gold_cvm (futuro)
  ref('fundos') JOIN ref('informe_diario')
  → rentabilidade, PL médio, captação líquida
```

### Questões-chave exploradas

| # | Questão | Resposta | Impacto |
|---|---------|---------|---------|
| 1 | Volume diário do informe | ~18k registros/dia (~250 fundos × dias úteis) | Justifica incremental; window 30d = ~540k/run |
| 2 | Freshness SLA | Cadastro: diário. Informe: mensal (CVM publica mensalmente) | DAG aguarda apenas dag_bronze_cvm_cadastro |
| 3 | Consumidor do Silver | Gold CVM (futuro) + Metabase | JOIN cadastro+informe no Gold |

---

## Decisões Chave

| # | Decisão | Rationale | Alternativa Rejeitada |
|---|---------|-----------|----------------------|
| 1 | Filtro `sit IN ('EM FUNCIONAMENTO NORMAL', 'EM LIQUIDAÇÃO')` | Critério semântico: "tem dados no informe diário" | Só `EM FUNCIONAMENTO NORMAL` (geraria gap no JOIN) |
| 2 | Sem SCD Tipo 2 | Valor analítico está no informe, não no histórico de atributos | dbt snapshots (complexidade não justificada no MVP) |
| 3 | Incremental com janela 30 dias | Custo fixo independente do volume histórico + cobre correções CVM | Full refresh (degradaria com volume crescente) |
| 4 | Modelos separados (fundos + informe) | Silver limpa, Gold compõe — padrão estabelecido no BCB | Modelo enriquecido Silver (JOIN na Silver) |
| 5 | FK `severity: warn` (não hard fail) | Dataset público externo pode ter inconsistências; dado histórico preservado | Filtro na Silver (descartaria dados válidos) |
| 6 | `captacao_liquida` na Silver | Todo Gold vai precisar — computa uma vez, consistente com derivadas BCB | Deixar para o Gold (duplicação em cada model Gold) |
| 7 | DAG aguarda só `dag_bronze_cvm_cadastro` | Informe é mensal; dbt incremental é no-op quando Bronze não muda | Aguardar ambas as DAGs Bronze diariamente |

---

## Features Removidas (YAGNI)

| Feature | Motivo da Remoção | Pode Adicionar Depois? |
|---------|-------------------|----------------------|
| SCD Tipo 2 (dbt snapshots) | Valor analítico do domínio é a série temporal do informe, não histórico de atributos | Sim — quando Gold precisar de análise temporal de gestores/classes |
| Modelo `informe_enriquecido` (JOIN Silver) | Duplica JOIN em cada run incremental; Gold tem flexibilidade para compor | Sim — se todos os modelos Gold precisarem dos mesmos atributos |
| 23 colunas excluídas do cadastro | `inf_taxa_perfm`, `inf_taxa_adm`, CNPJs de terceiros, flags booleanas, `rentab_fundo`, `publico_alvo`* — não usadas pelo Gold MVP | Sim — individualmente se o Gold precisar |
| Staging intermediário (stg_cvm_*) | BCB Silver não usou staging; o casting direto no model é suficiente | Sim — se os modelos crescerem em complexidade |
| DAG separada para informe mensal | Overhead operacional desnecessário; incremental é no-op nos dias sem novos dados | Sim — se o custo de queries diárias no Bronze se tornar relevante |

> *`publico_alvo` marcado como SHOULD no `/define` — útil para segmentar fundos exclusivos vs abertos no Gold.

---

## Validações Incrementais

| Seção | Status | Feedback | Ajustado? |
|-------|--------|---------|-----------|
| Estrutura de modelos (fundos + informe, colunas, derivadas) | ✅ Apresentada | `publico_alvo` como SHOULD; `captacao_liquida` confirmada | Sim — `publico_alvo` adicionado como SHOULD |
| Infraestrutura e DAG (migrations, dbt_project, sensor) | ✅ Apresentada | `dag_bronze_cvm_cadastro` confirmado; `dags/domain_funds/` confirmado | Sim — DAG_ID e diretório confirmados |

---

## Requisitos Sugeridos para o /define

### Problem Statement (Draft)
Transformar os dados brutos `bronze_cvm.cadastro` e `bronze_cvm.informe_diario` em modelos Silver validados, tipados e prontos para o Gold CVM calcular rentabilidade, PL médio e captação líquida de fundos ativos.

### Usuários-alvo

| Usuário | Necessidade |
|---------|------------|
| Gold CVM (modelo dbt futuro) | `fundos` e `informe_diario` limpos para JOIN e agregação |
| Analista de dados (Metabase) | Visão de fundos ativos com série temporal válida |

### Critérios de Sucesso (Draft)
- [ ] `silver_cvm.fundos` materializado com fundos `EM FUNCIONAMENTO NORMAL` e `EM LIQUIDAÇÃO`
- [ ] `silver_cvm.informe_diario` materializado como incremental com janela 30 dias
- [ ] `dbt test` passa sem erros (warnings de FK são aceitos)
- [ ] `captacao_liquida` presente e não-nula onde `captc_dia` e `resg_dia` não são nulos
- [ ] `dag_silver_cvm` executa com sucesso na UI do Airflow
- [ ] `dag_silver_cvm` aguarda `dag_bronze_cvm_cadastro` via ExternalTaskSensor

### Restrições Identificadas
- PostgreSQL 15 com particionamento nativo — dbt não conhece partições automaticamente; `source()` aponta para a tabela pai `informe_diario`
- `profiles.yml` usa `schema: silver_bcb` como default — `dbt_project.yml` deve ter `+schema: silver_cvm` no bloco `domain_cvm`
- `incremental_strategy: 'delete+insert'` — padrão dbt-postgres (não `merge`)
- DAG informe Bronze é `@monthly`; Silver não precisa aguardá-la diariamente — incremental é no-op nos dias sem novos dados

### Fora do Escopo (Confirmado)
- SCD Tipo 2 para histórico de situação do fundo
- Modelo enriquecido (JOIN cadastro+informe na Silver)
- dbt snapshots
- Staging intermediário (`stg_cvm_*`)
- Dados históricos pré-2024 no informe (Bronze tem, Silver herda naturalmente via incremental)

---

## Resumo da Sessão

| Métrica | Valor |
|---------|-------|
| Perguntas feitas | 5 |
| Abordagens exploradas | 10 (2 por pergunta) |
| Features removidas (YAGNI) | 5 |
| Validações completadas | 2 |
| Modelos dbt resultantes | 2 (`fundos` + `informe_diario`) |
| Linhas estimadas na Silver | ~2.500 (fundos) + 6,5M+ (informe) |

---

## Próximo Passo

**Pronto para:** `/define .claude/sdd/features/BRAINSTORM_SILVER_CVM.md`
