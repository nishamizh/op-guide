#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_PORT="${API_PORT:-8091}"
MCP_PORT="${MCP_PORT:-8092}"
WEB_PORT="${WEB_PORT:-4178}"
PY="${ROOT}/backend/.venv/bin/python"

if ! command -v pg_isready >/dev/null || ! pg_isready -h 127.0.0.1 -p 5432 >/dev/null; then
  echo "PostgreSQL is not accepting connections on 127.0.0.1:5432."
  echo "Start it, or run: docker compose up --build"
  exit 1
fi

mkdir -p "${ROOT}/.storage" "${ROOT}/.logs"
export DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://manualmind:manualmind@127.0.0.1:5432/manualmind}"
export STORAGE_LOCAL_PATH="${STORAGE_LOCAL_PATH:-${ROOT}/.storage}"
export MCP_SERVER_URL="${MCP_SERVER_URL:-http://127.0.0.1:${MCP_PORT}/mcp}"
export MCP_PORT

port_open() {
  python3 -c 'import socket,sys; s=socket.socket(); s.settimeout(0.3); raise SystemExit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1])))==0 else 1)' "$1"
}

if ! port_open "${MCP_PORT}"; then
  (cd "${ROOT}/mcp_servers" && PYTHONPATH="${ROOT}/mcp_servers" "${PY}" -m manufacturer) >"${ROOT}/.logs/mcp.log" 2>&1 &
  echo $! >"${ROOT}/.logs/mcp.pid"
fi
if ! port_open "${API_PORT}"; then
  (cd "${ROOT}/backend" && "${PY}" -m uvicorn app.main:app --host 0.0.0.0 --port "${API_PORT}") >"${ROOT}/.logs/api.log" 2>&1 &
  echo $! >"${ROOT}/.logs/api.pid"
fi
if ! port_open "${WEB_PORT}"; then
  (cd "${ROOT}/frontend" && npm run dev -- --host 0.0.0.0 --port "${WEB_PORT}" --strictPort) >"${ROOT}/.logs/web.log" 2>&1 &
  echo $! >"${ROOT}/.logs/web.pid"
fi

echo "API    http://127.0.0.1:${API_PORT}/api/health"
echo "MCP    http://127.0.0.1:${MCP_PORT}/mcp"
echo "Web    http://127.0.0.1:${WEB_PORT}"
echo "Logs   ${ROOT}/.logs"
