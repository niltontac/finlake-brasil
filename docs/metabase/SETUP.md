# Metabase BCB — Setup Guide

## Pré-requisitos

- `make up PROFILE=full` rodando
- `gold_bcb.macro_mensal` populada (`make migrate` + `dbt run --select macro_mensal macro_diario --target airflow`)

## 1. Wizard de primeiro acesso

Abrir `http://localhost:3030/setup` e preencher:

| Campo         | Valor sugerido         |
|---------------|------------------------|
| Email         | `admin@finlake.local`  |
| Password      | (escolher e salvar no `.env`) |
| First name    | Nilton                 |
| Organization  | FinLake Brasil         |

Na tela "Add your data" → clicar em **"I'll add my data later"**.

## 2. Conexão ao PostgreSQL

Admin panel → **Settings → Databases → Add a database**:

| Campo          | Valor          | Atenção                           |
|----------------|----------------|-----------------------------------|
| Database type  | PostgreSQL     |                                   |
| Display name   | FinLake Brasil |                                   |
| Host           | `postgres`     | ⚠️ Nunca `localhost` — rede Docker |
| Port           | `5432`         | ⚠️ Nunca `5433` — porta interna    |
| Database name  | `finlake`      | Valor de `POSTGRES_DB` no `.env`  |
| Username       | `postgres`     | Valor de `POSTGRES_USER`          |
| Password       | (ver `.env`)   | Valor de `POSTGRES_PASSWORD`      |
| Default schema | `gold_bcb`     | Lista macro_mensal diretamente    |

Clicar em **"Save"** — Metabase exibe "Connection successful".

## 3. Dashboard "BCB Macro"

New dashboard → Nome: **BCB Macro**

Adicionar 3 cards (New question → Simple question → FinLake Brasil → macro_mensal):

| Card                 | Tipo         | Eixo X | Eixo Y (Metric)                    |
|----------------------|--------------|--------|------------------------------------|
| SELIC real histórica | Line chart   | `date` | `selic_real`                       |
| SELIC vs Inflação    | Line chart   | `date` | `taxa_anual` + `acumulado_12m`     |
| PTAX médio mensal    | Line chart   | `date` | `ptax_media`                       |

Salvar o dashboard.

## 4. Export e versionamento

Após criar o dashboard, adicionar ao `.env`:

```dotenv
METABASE_ADMIN_EMAIL=admin@finlake.local
METABASE_ADMIN_PASSWORD=<senha_escolhida_no_wizard>
```

Exportar e versionar:

```bash
make metabase-export
git add docs/metabase/dashboard_bcb_macro.json
git commit -m "docs: export Metabase BCB Macro dashboard"
```

## Persistência

O setup (wizard, conexão, dashboards) persiste via volume Docker `metabase-data`.
Sobrevive a `make down && make up`. Só é perdido com `make reset` (remove volumes `-v`).

## Restaurar em novo ambiente

```bash
# 1. Subir containers
make up PROFILE=full

# 2. Completar wizard e recriar conexão manualmente (SETUP.md seções 1 e 2)

# 3. Importar dashboard via UI:
#    Settings → Admin → Import → selecionar docs/metabase/dashboard_bcb_macro.json
```
