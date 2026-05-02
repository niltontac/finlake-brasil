# DEFINE: METABASE_CVM — Dashboards de Fundos de Investimento

> Fechar o ciclo Medallion CVM com 3 dashboards Metabase sobre `gold_cvm.fundo_mensal`,
> incluindo cross-domain BCB × CVM e script de export versionado — artefato final de portfólio.

## Metadata

| Atributo | Valor |
|----------|-------|
| **Feature** | METABASE_CVM |
| **Data** | 2026-04-30 |
| **Autor** | define-agent |
| **Status** | ✅ Shipped |
| **Clarity Score** | 15/15 |
| **Origem** | BRAINSTORM_METABASE_CVM.md (2026-04-30) |

---

## Problem Statement

O domínio CVM tem a cadeia Medallion completa (Bronze → Silver → Gold) mas nenhuma camada
de visualização: analistas não conseguem responder "quais fundos superaram a SELIC em 2024?"
sem SQL manual, e o portfólio não demonstra o pipeline end-to-end de forma navegável.
Dois artefatos faltam para fechar o ciclo: dashboards Metabase prontos para consumo e
JSONs exportados e versionados no repositório.

---

## Target Users

| Usuário | Papel | Necessidade |
|---------|-------|-------------|
| Analista financeiro (Metabase) | Consumidor analítico | Navegar performance de fundos vs. SELIC/IPCA sem escrever SQL — filtrar por tipo, gestor, período |
| Engenheiro de dados (portfólio) | Builder / demonstração | Evidenciar pipeline Medallion completo com cross-domain CVM × BCB como artefato concreto para recrutadores |

---

## Goals

| Prioridade | Goal |
|------------|------|
| **MUST** | Dashboard `CVM — Visão Geral`: 4 cards de `fundo_mensal` (PL, captação, cotistas, contagem de fundos) |
| **MUST** | Dashboard `CVM — Rentabilidade`: 5 cards (top 10 fundos, alpha SELIC/IPCA por tipo, histograma, top gestores) |
| **MUST** | Dashboard `CVM — Fundos vs Macro`: 4 cards cross-domain com JOIN `fundo_mensal × macro_mensal` |
| **MUST** | Script `export_metabase_cvm.sh` exportando 3 JSONs para `docs/metabase/` via API |
| **MUST** | `make metabase-export-cvm` executando o script com vars do `.env` |
| **SHOULD** | `make metabase-export-all` encadeando BCB + CVM sem alterar script BCB existente |
| **SHOULD** | `docs/metabase/SETUP_CVM.md` com valores de conexão, filtros e SQL de exemplo para cards com JOIN |
| **COULD** | 3 JSONs gerados e commitados como evidência final de portfólio |

---

## Success Criteria

- [ ] 3 dashboards criados no Metabase com os nomes exatos: `CVM — Visão Geral`, `CVM — Rentabilidade`, `CVM — Fundos vs Macro`
- [ ] 13 cards totais distribuídos: 4 + 5 + 4 (conforme especificado no BRAINSTORM)
- [ ] Todos os dashboards carregam sem erro no Metabase (`localhost:3030`)
- [ ] Cards de `rentabilidade_mes_pct` aplicam filtro `BETWEEN -100 AND 500` — sem valores outlier visíveis
- [ ] Filtro global `meses_com_dados >= 6` ativo em todos os dashboards
- [ ] `make metabase-export-cvm` gera 3 arquivos JSON válidos (`python3 -m json.tool` sem erro)
- [ ] Script não altera `export_metabase.sh` existente — zero regressão no METABASE_BCB
- [ ] Nenhuma credencial hardcoded no script — tudo via variáveis de ambiente do `.env`
- [ ] Cards com JOIN `fundo_mensal × macro_mensal` retornam em < 5s

---

## Acceptance Tests

### AT-001 — Dashboard Visão Geral carrega

```
Dado: Metabase rodando, gold_cvm.fundo_mensal populada
Quando: Abrir dashboard "CVM — Visão Geral"
Então: 4 cards renderizados sem erro, PL total visível por tp_fundo ao longo de 2024
```

### AT-002 — Card de Rentabilidade sem outliers

```
Dado: Dashboard "CVM — Rentabilidade" aberto
Quando: Visualizar histograma de rentabilidade_mes_pct
Então: Escala entre -100% e 500% — nenhum valor acima de 500 visível
```

### AT-003 — Top gestores por alpha SELIC

```
Dado: Dashboard "CVM — Rentabilidade" com filtro tp_fundo livre
Quando: Ver card "Top 10 gestores por Alpha SELIC"
Então: Tabela exibe gestor, count(cnpj_fundo), avg(alpha_selic), avg(vl_patrim_liq_medio)
      ordenada por avg(alpha_selic) DESC
```

### AT-004 — Card estrela: % fundos que bateram SELIC

```
Dado: Dashboard "CVM — Fundos vs Macro" aberto
Quando: Ver card "% fundos que bateram SELIC no mês"
Então: Série temporal de 12 pontos (jan-dez 2024) com percentual entre 0% e 100%
```

### AT-005 — JOIN cross-domain no Metabase

```
Dado: Card "Rentabilidade média de mercado vs SELIC" usando SQL manual
Quando: Executar query com JOIN gold_cvm.fundo_mensal × gold_bcb.macro_mensal
Então: Linha dupla com avg(rentabilidade_mes_pct) e taxa_anual_bcb no mesmo gráfico, 12 pontos
```

### AT-006 — Script de export

```
Dado: 3 dashboards criados com nomes exatos, .env com credenciais
Quando: make metabase-export-cvm
Então: 3 arquivos gerados em docs/metabase/; python3 -m json.tool valida cada um sem erro
```

### AT-007 — Idempotência do script

```
Dado: 3 JSONs já existem em docs/metabase/
Quando: make metabase-export-cvm (segunda execução)
Então: Arquivos sobrescritos sem erro — nenhuma duplicata criada
```

### AT-008 — Zero regressão no METABASE_BCB

```
Dado: export_metabase.sh existente
Quando: make metabase-export-all
Então: BCB JSON exportado com sucesso; CVM JSONs também exportados; sem erro em nenhum
```

---

## Constraints

| Constraint | Descrição |
|------------|-----------|
| **Infraestrutura herdada** | Conexão `FinLake Brasil` já configurada (`host=postgres`, `db=finlake`, `schema=gold_bcb`) — A-001 abaixo |
| **Sem automação de criação** | Cards criados manualmente na UI — API Metabase de criação tem > 300 linhas, sem ganho de portfólio |
| **Sem nova conexão** | Usar conexão existente com prefixo `gold_cvm.` no SQL; segunda conexão apenas como fallback |
| **Gold intacto** | Filtros de outlier aplicados apenas nos cards SQL — nenhuma VIEW ou migration adicional |
| **Script BCB preservado** | `export_metabase.sh` não é alterado — `export_metabase_cvm.sh` é script independente |
| **Fonte: fundo_mensal** | `gold_cvm.fundo_diario` (6.5M rows) excluído dos dashboards — granularidade diária desnecessária para MVP |

---

## Assumptions (Pré-Validação Obrigatória)

| ID | Assumption | Status | Impacto se falsa |
|----|------------|--------|-----------------|
| **A-001** | Conexão `FinLake Brasil` aceita `gold_cvm.` como prefixo nos cards SQL — `SELECT * FROM gold_cvm.fundo_mensal LIMIT 1` funciona | **⚠️ Validar manualmente no Metabase antes do /build** | Criar segunda conexão com `default schema = gold_cvm` no admin panel |
| A-002 | JOIN `fundo_mensal × macro_mensal` via `ano_mes` funciona no SQL Question do Metabase | Validar durante build (AT-005) | Pode exigir `CAST(ano_mes AS date)` explícito |
| A-003 | `alpha_selic` e `alpha_ipca` têm valores numéricos válidos para fundos com `meses_com_dados >= 6` | Validar — cobertura confirmada em 99.58% no smoke test GOLD_CVM | `COALESCE(alpha_selic, 0)` como fallback |
| A-004 | Volume `metabase-data` persiste dashboards BCB — sem reset necessário | Confirmado — volume declarado no docker-compose.yml desde METABASE_BCB | Wizard recomeça do zero — BCB e CVM dashboards perdidos |
| A-005 | Script encontra dashboards pelos nomes exatos definidos neste DEFINE | Validar ao final do build | Listar todos os dashboards via `GET /api/dashboard` para debug |

> **Bloqueador de /build:** A-001 deve ser validada manualmente antes de iniciar o /design.
> Testar no Metabase: SQL Questions → `SELECT * FROM gold_cvm.fundo_mensal LIMIT 1`.
> Se falhar: ir em Admin → Databases → FinLake Brasil → editar → adicionar `gold_cvm` ao `additional_connection_options` ou criar segunda conexão.

---

## Out of Scope

| Item | Motivo |
|------|--------|
| Automação de criação de cards via API | UI faz em 15 min; API são 300+ linhas sem ganho de portfólio |
| Script de import/restore de JSONs | JSON exportado já é o artefato de reprodutibilidade |
| Dashboard por fundo individual (drill por CNPJ) | `fundo_diario` tem 6.5M rows — feature separada se necessário |
| Collections e permissões Metabase | Ambiente local single-user |
| Relatórios agendados | Fora do escopo de portfólio local |
| `gold_cvm.fundo_diario` como fonte de cards | Granularidade mensal suficiente para MVP |
| Refatoração de `export_metabase.sh` | Artefato em produção — não tocar |

---

## Dados e Fontes

| Tabela | Rows | Grain | Cards que usam |
|--------|------|-------|----------------|
| `gold_cvm.fundo_mensal` | 312.772 | (cnpj_fundo, ano_mes) | Todos os 13 cards |
| `gold_bcb.macro_mensal` | 315 | ano_mes | Dashboard 3: 2 cards com JOIN SQL |

**Filtros padrão documentados em SETUP_CVM.md:**
- `meses_com_dados >= 6` — exclui fundos com histórico muito curto
- `rentabilidade_mes_pct BETWEEN -100 AND 500` — exclui outliers extremos nos cards de rentabilidade
- `tp_fundo` (multi-select global) — segmentação por tipo de fundo
- `ano_mes` range (global) — recorte temporal

---

## Estrutura de Arquivos

```
scripts/
├── export_metabase.sh              ← EXISTENTE (BCB — não alterar)
└── export_metabase_cvm.sh          ← NOVO

docs/metabase/
├── SETUP.md                        ← EXISTENTE (BCB)
├── SETUP_CVM.md                    ← NOVO
├── dashboard_bcb_macro.json        ← EXISTENTE
├── dashboard_cvm_visao_geral.json  ← GERADO após setup manual
├── dashboard_cvm_rentabilidade.json ← GERADO após setup manual
└── dashboard_cvm_fundos_macro.json ← GERADO após setup manual

Makefile
  ├── metabase-export-cvm           ← NOVO
  └── metabase-export-all           ← NOVO
```

---

## Clarity Score Breakdown

| Dimensão | Pontos | Justificativa |
|----------|--------|---------------|
| Problem | 3/3 | Específico: pipeline completo sem visualização |
| Users | 3/3 | 2 personas com pain points distintos |
| Goals | 3/3 | MUST/SHOULD/COULD com artefatos nomeados |
| Success | 3/3 | 9 critérios mensuráveis + 8 ATs testáveis |
| Scope | 3/3 | In/out scope explícito; 8 itens YAGNI removidos |
| **Total** | **15/15** | |

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-30 | define-agent | Versão inicial a partir de BRAINSTORM_METABASE_CVM.md |
