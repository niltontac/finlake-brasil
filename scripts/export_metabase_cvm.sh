#!/usr/bin/env bash
# Exporta 3 dashboards CVM do Metabase para docs/metabase/
# Uso: make metabase-export-cvm (ou bash scripts/export_metabase_cvm.sh)
# Requer: METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env

set -euo pipefail

METABASE_URL="${METABASE_URL:-http://localhost:3030}"
EMAIL="${METABASE_ADMIN_EMAIL:?Defina METABASE_ADMIN_EMAIL no .env}"
PASSWORD="${METABASE_ADMIN_PASSWORD:?Defina METABASE_ADMIN_PASSWORD no .env}"
OUTPUT_DIR="docs/metabase"

# Formato: "Nome do Dashboard:nome_do_arquivo.json"
DASHBOARDS=(
    "CVM — Visão Geral:dashboard_cvm_visao_geral.json"
    "CVM — Rentabilidade:dashboard_cvm_rentabilidade.json"
    "CVM — Fundos vs Macro:dashboard_cvm_fundos_macro.json"
)

mkdir -p "${OUTPUT_DIR}"

echo "→ Autenticando em ${METABASE_URL}..."
TOKEN=$(curl -sf -X POST "${METABASE_URL}/api/session" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
    | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

for entry in "${DASHBOARDS[@]}"; do
    NAME="${entry%%:*}"
    FILE="${OUTPUT_DIR}/${entry##*:}"

    echo "→ Buscando dashboard '${NAME}'..."
    DASHBOARD_ID=$(curl -sf "${METABASE_URL}/api/dashboard" \
        -H "X-Metabase-Session: ${TOKEN}" \
        | python3 -c "
import sys, json
dashboards = json.load(sys.stdin)
match = next((d for d in dashboards if d['name'] == '${NAME}'), None)
if not match:
    names = [d['name'] for d in dashboards]
    raise SystemExit(f'Dashboard \"${NAME}\" nao encontrado. Disponiveis: {names}')
print(match['id'])
")

    echo "→ Exportando dashboard ID=${DASHBOARD_ID}..."
    curl -sf "${METABASE_URL}/api/dashboard/${DASHBOARD_ID}" \
        -H "X-Metabase-Session: ${TOKEN}" \
        | python3 -m json.tool > "${FILE}"

    echo "✓ ${FILE}"
done

echo ""
echo "Commit com:"
echo "  git add docs/metabase/dashboard_cvm_*.json"
echo "  git commit -m 'docs: export Metabase CVM dashboards'"
