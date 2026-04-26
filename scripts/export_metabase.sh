#!/usr/bin/env bash
# Exporta dashboard Metabase "BCB Macro" para docs/metabase/dashboard_bcb_macro.json
# Uso: make metabase-export (ou bash scripts/export_metabase.sh)
# Requer: METABASE_ADMIN_EMAIL e METABASE_ADMIN_PASSWORD no .env

set -euo pipefail

METABASE_URL="${METABASE_URL:-http://localhost:3030}"
EMAIL="${METABASE_ADMIN_EMAIL:?Defina METABASE_ADMIN_EMAIL no .env}"
PASSWORD="${METABASE_ADMIN_PASSWORD:?Defina METABASE_ADMIN_PASSWORD no .env}"
DASHBOARD_NAME="BCB Macro"
OUTPUT_DIR="docs/metabase"
OUTPUT_FILE="${OUTPUT_DIR}/dashboard_bcb_macro.json"

mkdir -p "${OUTPUT_DIR}"

echo "→ Autenticando em ${METABASE_URL}..."
TOKEN=$(curl -sf -X POST "${METABASE_URL}/api/session" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${EMAIL}\",\"password\":\"${PASSWORD}\"}" \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

echo "→ Buscando dashboard '${DASHBOARD_NAME}'..."
DASHBOARD_ID=$(curl -sf "${METABASE_URL}/api/dashboard" \
  -H "X-Metabase-Session: ${TOKEN}" \
  | python3 -c "
import sys, json
dashboards = json.load(sys.stdin)
match = next((d for d in dashboards if d['name'] == '${DASHBOARD_NAME}'), None)
if not match:
    names = [d['name'] for d in dashboards]
    raise SystemExit(f'Dashboard \"${DASHBOARD_NAME}\" nao encontrado. Disponiveis: {names}')
print(match['id'])
")

echo "→ Exportando dashboard ID=${DASHBOARD_ID}..."
curl -sf "${METABASE_URL}/api/dashboard/${DASHBOARD_ID}" \
  -H "X-Metabase-Session: ${TOKEN}" \
  | python3 -m json.tool > "${OUTPUT_FILE}"

echo "✓ Dashboard exportado: ${OUTPUT_FILE}"
echo "  Commit com: git add ${OUTPUT_FILE} && git commit -m 'docs: export Metabase BCB Macro dashboard'"
