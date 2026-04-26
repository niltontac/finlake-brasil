# DEFINE: Metabase BCB — Visualização Macroeconômica

> Fechar o ciclo Bronze → Silver → Gold → Visualização do domínio BCB: Metabase
> conectado ao `gold_bcb`, 1 dashboard com SELIC real, PTAX e IPCA acumulado,
> JSON exportado e versionado para reprodutibilidade zero-config.

## Metadata

| Atributo          | Valor                                            |
|-------------------|--------------------------------------------------|
| **Feature**       | METABASE_BCB                                     |
| **Data**          | 2026-04-26                                       |
| **Autor**         | Nilton Coura                                     |
| **Status**        | Ready for Design                                 |
| **Clarity Score** | 14/15                                            |
| **Origem**        | BRAINSTORM_METABASE_BCB.md (2026-04-25)          |
| **Upstream**      | GOLD_BCB (shipped 2026-04-24)                    |

---

## Problem Statement

O ciclo Medallion do domínio BCB está incompleto: Bronze → Silver → Gold estão
operacionais, mas sem camada de visualização os dados são invisíveis para
stakeholders e recrutadores. O Metabase está declarado em `compose.metabase.yml`
mas nunca configurado — sem conexão ao `gold_bcb`, sem dashboards, sem artefato
de portfólio reproduzível. Adicionalmente, `compose.metabase.yml` não declara
volume para os metadados H2 do Metabase, então qualquer `docker compose down`
destrói o setup — wizard, conexão e dashboards precisariam ser refeitos do zero.

---

## Target Users

| Usuário | Papel | Pain Point |
|---------|-------|------------|
| Nilton Coura | Data Engineer / dono da plataforma | Ciclo Medallion incompleto sem visualização; `make down` destroça setup Metabase |
| Recrutadores / stakeholders | Consumidores do portfólio | Precisam ver o dashboard funcionando sem configurar nada; JSON exportado é o artefato |

---

## Goals

| Prioridade | Goal |
|------------|------|
| **MUST** | Volume `metabase-data` adicionado ao `compose.metabase.yml` — setup H2 persiste entre restarts |
| **MUST** | Wizard completado: admin email, senha, org name, timezone `America/Sao_Paulo` |
| **MUST** | Conexão `FinLake Brasil` configurada: `host=postgres, port=5432, db=finlake, schema=gold_bcb` |
| **MUST** | Dashboard `BCB Macro` com 3 charts de `gold_bcb.macro_mensal` |
| **MUST** | `scripts/export_metabase.sh` — autentica via API, exporta JSON do dashboard |
| **MUST** | `make metabase-export` executando o script com vars do `.env` |
| **MUST** | `docs/metabase/dashboard_bcb_macro.json` versionado no repositório |
| **SHOULD** | `docs/metabase/SETUP.md` — guia de conexão com valores corretos e aviso `host=postgres` |
| **SHOULD** | `.env.example` atualizado com `METABASE_ADMIN_EMAIL` e `METABASE_ADMIN_PASSWORD` |

---

## Success Criteria

- [ ] `localhost:3030` abre o Metabase — health check retorna `{"status":"ok"}`
- [ ] Conexão `FinLake Brasil` salva sem erro — Metabase exibe "Connection successful"
- [ ] `gold_bcb.macro_mensal` visível em "Browse data" sem sync manual
- [ ] Dashboard `BCB Macro` abre com 3 charts — dados aparecem (não vazio, não erro)
- [ ] `make metabase-export` executa sem erro — `docs/metabase/dashboard_bcb_macro.json` gerado
- [ ] JSON válido: `python3 -m json.tool docs/metabase/dashboard_bcb_macro.json` retorna sem erro
- [ ] JSON contém os 3 cards do dashboard (verificável via `jq '.dashcards | length'`)
- [ ] `docker compose down && docker compose up -d` — setup Metabase persiste (volume H2)

---

## Acceptance Tests

| ID | Cenário | Given | When | Then |
|----|---------|-------|------|------|
| AT-001 | Metabase health | Container rodando (`make up PROFILE=full`) | `curl localhost:3030/api/health` | `{"status":"ok"}` |
| AT-002 | Conexão PostgreSQL | Metabase com wizard completado | Admin panel → "Add database" com `host=postgres` | "Connection successful" — sem timeout |
| AT-003 | Schema visível | Conexão salva (AT-002) | "Browse data" → FinLake Brasil | `gold_bcb.macro_mensal` e `gold_bcb.macro_diario` listadas |
| AT-004 | Dashboard com dados | Dashboard `BCB Macro` criado | Abrir dashboard | 3 charts renderizam com dados (SELIC real ~10.65% em mar/2026) |
| AT-005 | Export executa | `.env` com `METABASE_ADMIN_EMAIL` e `METABASE_ADMIN_PASSWORD` | `make metabase-export` | Exit code 0, arquivo `docs/metabase/dashboard_bcb_macro.json` criado |
| AT-006 | JSON válido | AT-005 executado | `python3 -m json.tool docs/metabase/dashboard_bcb_macro.json` | Sem erro de parse |
| AT-007 | JSON contém cards | AT-006 válido | `jq '.dashcards \| length' docs/metabase/dashboard_bcb_macro.json` | Retorna `3` |
| AT-008 | Persistência H2 | Volume `metabase-data` declarado | `docker compose down && docker compose up -d` | Metabase abre diretamente sem wizard — conexão e dashboard preservados |

---

## Out of Scope

- **Script de import/restore** — export garante reprodutibilidade; import via UI é trivial
- **Dashboard `macro_diario`** — deferido; diário fica disponível para exploração ad-hoc
- **Automação via API** (`POST /api/database`, `POST /api/card`) — UI é 10x mais rápida para 3 charts
- **Collections e permissões** — ambiente local single-user, sem necessidade
- **Relatórios agendados** — fora do escopo de portfólio local
- **`ptax_variacao_mensal_pct` no dashboard** — campo disponível, mas deferred; 3 charts é suficiente para MVP
- **Metabase com PostgreSQL externo** (em vez de H2) — H2 é suficiente para ambiente local de portfólio

---

## Constraints

| Tipo | Constraint | Impacto |
|------|------------|---------|
| Técnico | `host=postgres` na conexão (rede Docker) — `localhost` não funciona no container | Conexão falha silenciosamente se usar localhost |
| Técnico | H2 sem volume = setup perdido em `docker compose down` — volume `metabase-data` é obrigatório | Wizard e conexão refeitos a cada restart |
| Técnico | `GET /api/dashboard/:id` exporta JSON completo — formato pode variar entre versões do Metabase | JSON de versão 0.49 pode não importar em 0.50+ |
| Portfólio | JSON versionado em `docs/metabase/` deve ser self-contained — recrutador não precisa do Metabase para entender o artefato | `SETUP.md` documenta o contexto |
| Segurança | `METABASE_ADMIN_PASSWORD` no `.env` — nunca hardcoded no script | Script lê via variável de ambiente |

---

## Technical Context

| Aspecto | Valor | Notas |
|---------|-------|-------|
| **Metabase version** | `metabase/metabase:latest` | Verificar em `/api/session/properties` após setup |
| **H2 data path** | `/metabase-data` (dentro do container) | Volume nomeado `metabase-data` monta neste path |
| **Conexão** | `postgres:5432` (rede Docker interna) | NÃO `localhost:5433` |
| **Schema padrão** | `gold_bcb` | Metabase lista tabelas diretamente |
| **Script** | `scripts/export_metabase.sh` | Bash + `curl` + `python3 -m json.tool` |
| **Makefile target** | `make metabase-export` | Vars do `.env` via `-include .env; export` |
| **JSON output** | `docs/metabase/dashboard_bcb_macro.json` | Versionado no repo |

---

## Data Contract

### Source

| Tabela | Schema | Rows | Grain | Colunas usadas no dashboard |
|--------|--------|------|-------|-----------------------------|
| `macro_mensal` | `gold_bcb` | 315 | Mensal (2000-01 → 2026-03) | `date`, `selic_real`, `taxa_anual`, `acumulado_12m`, `ptax_media` |

### Dashboard — `BCB Macro`

| Chart | Tipo Metabase | X-axis | Y-axis | Filtro padrão |
|-------|---------------|--------|--------|---------------|
| SELIC real histórica | Line chart | `date` | `selic_real` (%) | Nenhum |
| SELIC vs Inflação | Line chart (dual) | `date` | `taxa_anual` + `acumulado_12m` (%) | Nenhum |
| PTAX médio mensal | Line chart | `date` | `ptax_media` (R$/USD) | Nenhum |

---

## Assumptions

| ID | Assumption | Se errada, impacto | Validado? |
|----|------------|-------------------|-----------|
| A-001 | `host=postgres` resolve dentro da rede Docker `finlake-net` | Conexão falha — usar `docker inspect finlake-postgres` para IP como fallback | [ ] |
| A-002 | Volume `metabase-data` em `/metabase-data` persiste dados H2 entre restarts | Setup perdido — verificar path correto no Metabase docs | [ ] |
| A-003 | `GET /api/dashboard/:id` retorna JSON completo com `dashcards` e layout | JSON incompleto — `dashcards` pode ser array vazio em algumas versões | [ ] |
| A-004 | `default schema = gold_bcb` faz Metabase listar `macro_mensal` sem sync manual | Sync necessário — verificar em "Browse data" após salvar | [ ] |

---

## Pré-requisitos Bloqueantes

### PRE-01 — Volume H2 no `compose.metabase.yml`

Adicionar antes de iniciar o setup (senão o wizard será perdido no próximo restart):

```yaml
services:
  metabase:
    # ... config existente ...
    volumes:
      - metabase-data:/metabase-data

volumes:
  metabase-data:
```

### PRE-02 — `.env` com credenciais Metabase

Após completar o wizard, adicionar ao `.env`:

```dotenv
METABASE_ADMIN_EMAIL=admin@finlake.local
METABASE_ADMIN_PASSWORD=<senha_escolhida_no_wizard>
```

### PRE-03 — Gold BCB populada (✅ já validado)

`gold_bcb.macro_mensal` com 315 registros — confirmado no AT-003 do GOLD_BCB.

---

## Clarity Score Breakdown

| Elemento | Score | Justificativa |
|----------|-------|---------------|
| Problem | 3/3 | Ciclo incompleto + H2 sem volume — dois problemas específicos e concretos |
| Users | 2/3 | Nilton explícito; recrutadores como consumidores secundários documentados |
| Goals | 3/3 | MUST/SHOULD priorizados, volume H2 adicionado como gap do Brainstorm |
| Success | 3/3 | ATs testáveis com comandos exatos (`curl`, `jq`, `python3 -m json.tool`) |
| Scope | 3/3 | 7 features explicitamente fora do escopo; H2 vs PostgreSQL externo incluído |
| **Total** | **14/15** | |

**Mínimo para prosseguir: 12/15 ✅**

---

## Open Questions

Nenhuma — pronto para Design.

A-001 a A-004 devem ser validadas no início do Build:
- A-001: `docker inspect finlake-postgres` confirma resolução de nome
- A-002: `docker exec finlake-metabase ls /metabase-data` confirma path H2
- A-003: verificar presença de `dashcards` no JSON exportado
- A-004: verificar "Browse data" após salvar conexão

---

## Revision History

| Versão | Data | Autor | Mudanças |
|--------|------|-------|---------|
| 1.0 | 2026-04-26 | define-agent | Versão inicial from BRAINSTORM_METABASE_BCB.md — adicionado PRE-01 (volume H2) como gap do Brainstorm |

---

## Next Step

**Pronto para:** `/design .claude/sdd/features/DEFINE_METABASE_BCB.md`
