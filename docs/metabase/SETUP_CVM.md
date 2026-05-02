# Metabase CVM — Setup Guide

## Pré-requisitos

- `make up PROFILE=full` rodando (`localhost:3030` acessível)
- `gold_cvm.fundo_mensal` populada com 312.772 registros
- `gold_bcb.macro_mensal` populada com 315 registros
- Conexão `db_finlake_brasil` configurada no Metabase (✅ existente do METABASE_BCB)
- `.env` com `METABASE_ADMIN_EMAIL` e `METABASE_ADMIN_PASSWORD`
- `requests` disponível: `python3 -c "import requests"` (ou `uv add requests`)

## 1. Criar dashboards e cards automaticamente

```bash
make metabase-setup-cvm
```

Saída esperada:

```
→ Autenticando em http://localhost:3030...
→ Buscando conexão 'db_finlake_brasil'...
  Conexão encontrada: ID=1
→ Criando 13 cards SQL...
  ✓ [CVM — Visão Geral] Fundos com dados suficientes (ID=42)
  ✓ [CVM — Visão Geral] PL total por tipo de fundo (ID=43)
  ...
→ Criando 3 dashboards...
  ✓ CVM — Visão Geral (ID=4)
  ✓ CVM — Rentabilidade (ID=5)
  ✓ CVM — Fundos vs Macro (ID=6)
→ Adicionando cards aos dashboards...
  ✓ 4 cards adicionados a 'CVM — Visão Geral'
  ✓ 5 cards adicionados a 'CVM — Rentabilidade'
  ✓ 4 cards adicionados a 'CVM — Fundos vs Macro'

✓ Setup concluído! Dashboards disponíveis em:
  http://localhost:3030/dashboard/4 — CVM — Visão Geral
  http://localhost:3030/dashboard/5 — CVM — Rentabilidade
  http://localhost:3030/dashboard/6 — CVM — Fundos vs Macro

Próximo passo: make metabase-export-cvm
```

## 2. Verificar dashboards

Abrir as URLs impressas pelo script e confirmar:

| Dashboard | Cards esperados | Check |
|-----------|-----------------|-------|
| CVM — Visão Geral | 4 cards (scalar + 3 gráficos) | |
| CVM — Rentabilidade | 5 cards (2 tabelas + 3 gráficos) | |
| CVM — Fundos vs Macro | 4 cards (3 linhas + 1 barra) | |

**Card destaque:** `% fundos que bateram a SELIC no mês` — série temporal jan-dez 2024
com percentual entre 0% e 100%.

## 3. Filtros interativos (passo manual — opcional)

O script não cria filtros de dashboard. Para adicionar:

Dashboard → ✏️ (Edit) → **Add a filter**:

| Filtro | Tipo | Campo |
|--------|------|-------|
| Tipo de fundo | String | `tp_fundo` |
| Período | Date | `ano_mes` |

> O filtro `rentabilidade_mes_pct BETWEEN -100 AND 500` está embutido no SQL dos cards
> de rentabilidade — não é filtro de dashboard.

## 4. Export e versionamento

```bash
make metabase-export-cvm
```

Validar os JSONs:

```bash
for f in docs/metabase/dashboard_cvm_*.json; do
  python3 -m json.tool "$f" > /dev/null && echo "✓ $f"
done
```

Versionar:

```bash
git add docs/metabase/dashboard_cvm_*.json
git commit -m "docs: export Metabase CVM dashboards"
```

## 5. Persistência

Setup e dashboards persistem via volume Docker `metabase-data`.
Sobrevive a `make down && make up`. Perdido apenas com `make reset`.

Se os dashboards forem perdidos, basta re-executar `make metabase-setup-cvm`.

## 6. Troubleshooting

| Problema | Causa | Solução |
|----------|-------|---------|
| `ModuleNotFoundError: requests` | Dependência ausente | `uv add requests` ou `pip install requests` |
| `Conexão 'db_finlake_brasil' não encontrada` | Nome divergente no Metabase | Verificar em Admin → Databases; ajustar `DB_NAME` no script se necessário |
| `gold_cvm.` não reconhecido no card | Permissão de schema | `GRANT USAGE ON SCHEMA gold_cvm TO postgres;` no PostgreSQL |
| `401 Unauthorized` | Credenciais erradas | Verificar `METABASE_ADMIN_EMAIL` e `METABASE_ADMIN_PASSWORD` no `.env` |
| `PUT /api/dashboard/{id}/cards` 404 | Versão Metabase incompatível | Verificar versão: Admin → Settings → About |
| Script exporta dashboards BCB em vez de CVM | Nome de dashboard diferente | Checar nomes exatos em `localhost:3030` → All Dashboards |
