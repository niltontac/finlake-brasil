# BUILD_REPORT — METABASE_CVM

| Campo          | Valor                                        |
|----------------|----------------------------------------------|
| **Feature**    | METABASE_CVM                                 |
| **Status**     | ✅ Concluído (artefatos de código)            |
| **Data**       | 2026-05-01                                   |
| **Engenheiro** | Nilton Coura                                 |
| **Referência** | DESIGN_METABASE_CVM.md / DEFINE_METABASE_CVM.md |

---

## Resumo

Implementação dos artefatos de código para a camada de visualização CVM:
script de export de 3 dashboards Metabase, guia de setup completo com SQL
copy-paste ready de todos os 13 cards, e 2 targets Makefile.

A criação dos dashboards na UI do Metabase e o export dos JSONs são etapas
manuais documentadas em `docs/metabase/SETUP_CVM.md`.

---

## Artefatos Criados

| # | Arquivo | Ação | Status |
|---|---------|------|--------|
| 1 | `scripts/export_metabase_cvm.sh` | Criado | ✅ |
| 2 | `docs/metabase/SETUP_CVM.md` | Criado | ✅ |
| 3 | `Makefile` | Modificado (+2 targets) | ✅ |

---

## Verificações Executadas

### Script export_metabase_cvm.sh

```bash
bash -n scripts/export_metabase_cvm.sh
# → syntax OK
```

### Makefile targets

```bash
grep -A2 "metabase-export" Makefile
# → metabase-export-cvm e metabase-export-all presentes com padrão correto
```

### make help

```
metabase-export-cvm  Exporta 3 dashboards CVM para docs/metabase/
metabase-export-all  (aparece via target metabase-export — padrão Makefile)
```

---

## Acceptance Tests

| AT | Tipo | Status |
|----|------|--------|
| AT-001 a AT-005 | Manual (UI Metabase) | Pendente — aguarda criação dos dashboards |
| AT-006 | `make metabase-export-cvm` | Pendente — aguarda dashboards criados |
| AT-007 | Idempotência do script | Pendente — aguarda AT-006 |
| AT-008 | `make metabase-export-all` | Pendente — aguarda AT-006 |

> Todos os ATs manuais são verificáveis seguindo `docs/metabase/SETUP_CVM.md`.

---

## Insight Arquitetural Documentado

**JOIN eliminado no Metabase (ADR-002):** Os 13 cards usam apenas
`gold_cvm.fundo_mensal`. As colunas `taxa_anual_bcb` e `acumulado_12m_ipca`
já estão materializadas pelo dbt (Gold JOIN feito na camada correta).
Dashboard 3 (Fundos vs Macro) não precisa de nenhum JOIN no Metabase.

---

## SQL Patterns Validados

Os 13 SQLs documentados no DESIGN e replicados no SETUP_CVM.md foram
revisados para:

- `BETWEEN -100 AND 500` em todos os cards de rentabilidade ✅
- `NULLIF(COUNT(*), 0)` no card 3.3 para proteção de divisão por zero ✅
- `COALESCE(gestor, 'Não informado')` nos cards com campo nullable ✅
- `meses_com_dados >= 6` em todos os 13 cards ✅
- `alpha_selic IS NOT NULL` nos cards de alpha (cobertura confirmada em 99.58%) ✅

---

## Métricas da Build

| Métrica | Valor |
|---------|-------|
| Artefatos de código criados | 2 |
| Artefatos modificados | 1 |
| Targets Makefile adicionados | 2 |
| Cards documentados (SQL) | 13 |
| Dashboards planejados | 3 |
| Bugs corrigidos no build | 0 |

---

## Próximos Passos (Setup Manual)

1. `make up PROFILE=full`
2. Seguir `docs/metabase/SETUP_CVM.md` para criar os 3 dashboards
3. `make metabase-export-cvm` → gera 3 JSONs em `docs/metabase/`
4. Validar JSONs: `python3 -m json.tool docs/metabase/dashboard_cvm_*.json`
5. Commit dos JSONs
6. `/ship .claude/sdd/features/DESIGN_METABASE_CVM.md`
