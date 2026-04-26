# BUILD REPORT: Metabase BCB — Visualização Macroeconômica

> Build concluído em 2026-04-26

## Metadata

| Atributo          | Valor                                            |
|-------------------|--------------------------------------------------|
| **Feature**       | METABASE_BCB                                     |
| **Data**          | 2026-04-26                                       |
| **Autor**         | Nilton Coura                                     |
| **Status**        | ✅ Build Complete (setup manual pendente)        |
| **DESIGN**        | DESIGN_METABASE_BCB.md                           |
| **Desvios**       | 0                                                |

---

## Tasks Executadas

| # | Arquivo | Ação | Status | Verificação |
|---|---------|------|--------|-------------|
| 1 | `docker/compose.metabase.yml` | Modify | ✅ | `volumes: metabase-data:/metabase-data` adicionado; YAML válido |
| 2 | `docker-compose.yml` | Modify | ✅ | `metabase-data: driver: local` em `volumes:` globais; YAML válido |
| 3 | `scripts/export_metabase.sh` | Create | ✅ | `bash -n` OK; `set -euo pipefail`; busca por nome; `:?` para vars obrigatórias |
| 4 | `docs/metabase/SETUP.md` | Create | ✅ | Guia completo com tabela de conexão e aviso `host=postgres` |
| 5 | `Makefile` | Modify | ✅ | Target `metabase-export` adicionado com `## docstring` |
| 6 | `.env.example` | Modify | ✅ | `METABASE_ADMIN_EMAIL` + `METABASE_ADMIN_PASSWORD` na seção Metabase |

**Total: 6/6 tasks concluídas**

> Item 7 (`docs/metabase/dashboard_bcb_macro.json`) é gerado manualmente via
> `make metabase-export` após o setup UI — não é criado pelo build agent.

---

## Validações

```
bash -n scripts/export_metabase.sh          → OK
YAML: docker/compose.metabase.yml           → OK
YAML: docker-compose.yml                    → OK
ruff check . (projeto completo)             → All checks passed!
pytest tests/ -q                            → 12 passed, 1 skipped in 0.74s
```

---

## Estrutura Final Criada

```
scripts/
└── export_metabase.sh                      ← NOVO

docs/
└── metabase/
    ├── SETUP.md                            ← NOVO
    └── dashboard_bcb_macro.json            ← PENDENTE (gerado via make metabase-export)

docker/
└── compose.metabase.yml                    ← MODIFICADO: volume metabase-data

docker-compose.yml                          ← MODIFICADO: metabase-data em volumes globais
Makefile                                    ← MODIFICADO: target metabase-export
.env.example                                ← MODIFICADO: METABASE_ADMIN_EMAIL + PASSWORD
```

---

## Desvios do DESIGN

Nenhum. Implementação 100% fiel ao DESIGN_METABASE_BCB.md.

---

## Setup Manual Pendente (ATs requerem container)

```bash
# PRE: aplicar novo volume ao container (recriação necessária)
make down
make up PROFILE=full

# Wizard: localhost:3030/setup
# Conexão: admin panel → Add database → host=postgres, port=5432, db=finlake, schema=gold_bcb
# Dashboard: "BCB Macro" com 3 charts de gold_bcb.macro_mensal

# Após setup:
echo "METABASE_ADMIN_EMAIL=admin@finlake.local" >> .env
echo "METABASE_ADMIN_PASSWORD=<senha>" >> .env
make metabase-export
git add docs/metabase/dashboard_bcb_macro.json
git commit -m "docs: export Metabase BCB Macro dashboard"
```

| AT | Critério | Status |
|----|----------|--------|
| AT-001 | `curl localhost:3030/api/health` → `{"status":"ok"}` | ⏳ Requer container |
| AT-002 | Conexão PostgreSQL — "Connection successful" | ⏳ Requer setup manual |
| AT-003 | `gold_bcb.macro_mensal` visível em "Browse data" | ⏳ Requer AT-002 |
| AT-004 | Dashboard "BCB Macro" — 3 charts com dados | ⏳ Requer setup manual |
| AT-005 | `make metabase-export` → exit code 0, JSON gerado | ⏳ Requer AT-004 |
| AT-006 | `python3 -m json.tool docs/metabase/dashboard_bcb_macro.json` → OK | ⏳ Requer AT-005 |
| AT-007 | `jq '.dashcards \| length'` → `3` | ⏳ Requer AT-005 |
| AT-008 | `make down && make up` → setup persiste (volume H2) | ⏳ Requer AT-004 |

---

## Próximo Passo

Executar setup manual seguindo `docs/metabase/SETUP.md`, depois:

```bash
make metabase-export
```

**Pronto para:** `/ship .claude/sdd/features/DEFINE_METABASE_BCB.md`
