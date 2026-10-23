.PHONY: dev api mcp web test eval lint migrate seed

API_PORT ?= 8091
MCP_PORT ?= 8092
WEB_PORT ?= 4178
PY ?= backend/.venv/bin/python
PIP ?= backend/.venv/bin/pip

dev:
	bash scripts/dev.sh

api:
	cd backend && ../$(PY) -m uvicorn app.main:app --host 0.0.0.0 --port $(API_PORT)

mcp:
	cd mcp_servers && MCP_PORT=$(MCP_PORT) PYTHONPATH=. ../$(PY) -m manufacturer

web:
	cd frontend && npm run dev -- --port $(WEB_PORT)

test:
	cd backend && ../$(PY) -m pytest -q
	cd frontend && npm test

eval:
	cd backend && ../$(PY) -m app.evals

lint:
	cd backend && ../$(PY) -m ruff check app tests
	cd frontend && npm run lint && npm run typecheck

migrate:
	cd backend && ../$(PY) -m alembic upgrade head

seed:
	cd backend && ../$(PY) -c "from app.db import session_scope; from app.seed.seed import seed_demo; \
import json; \
ctx = session_scope(); db = ctx.__enter__(); \
print(json.dumps(seed_demo(db, force=True))); \
ctx.__exit__(None, None, None)"
