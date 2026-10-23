# Deployment

ManualMind is three processes plus Postgres and object storage.

| Service | Host | Why |
| --- | --- | --- |
| `frontend/` | Vercel | Static Vite build and SPA routing |
| `backend/` | A persistent Python 3.12 container | SSE streams, background ingestion, LangGraph checkpoints |
| `mcp_servers/` | A persistent Python 3.12 container | Long-lived MCP HTTP server |
| PostgreSQL 16 + pgvector | Managed Postgres with TLS | Vectors, chat, traces, jobs, evaluations |
| Documents | S3-compatible object storage | Uploads must survive deploys |

Vercel serverless is the wrong place for Postgres, the MCP server, or the ingestion worker. The UI calls the API with `VITE_API_BASE_URL`. That is the only `VITE_` variable. Do not put `OPENAI_API_KEY`, `DATABASE_URL`, `MCP_SERVER_TOKEN`, or object-storage secrets in a `VITE_` name. Those belong in the API host's secret store.

Leave `VITE_API_BASE_URL` empty for local dev. The Vite server proxies `/api` to `127.0.0.1:8091`. A published page ignores a loopback API URL, because that address is the build machine and the visitor's browser reports it as "Failed to fetch". Set `VITE_API_BASE_URL` to the public FastAPI origin before building the Vercel site.

## Production environment

Frontend, in the Vercel project:

```
VITE_API_BASE_URL=https://api.example.com
```

Backend and worker, from `.env.production.example` (placeholders only):

```
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_FALLBACK_MODEL
OPENAI_EMBEDDING_MODEL
DATABASE_URL
MCP_SERVER_URL
CORS_ALLOWED_ORIGINS
OBJECT_STORAGE_BUCKET
OBJECT_STORAGE_ENDPOINT
OBJECT_STORAGE_ACCESS_KEY
OBJECT_STORAGE_SECRET_KEY
SESSION_SECRET
APP_ENV=production
```

Also set `DB_SSLMODE=require` (or `verify-ca` / `verify-full`), `AUTO_MIGRATE=false`, and `EMBED_WORKER=false` on the API if a separate worker process is running. `GET /api/ready` returns 503 until the database, pgvector column, object storage, CORS, session secret, and MCP URL are acceptable for production.

`CORS_ALLOWED_ORIGINS` is a comma-separated list of exact origins, for example `https://manualmind.example.com,https://your-project.vercel.app`. Methods are GET, POST, DELETE, and OPTIONS. Headers are Authorization, Content-Type, X-Tenant-Id, X-User-Id, and X-Request-Id. Credentials are enabled, so origins cannot be `*`. `CORS_ALLOW_VERCEL_PREVIEWS=true` also allows `https://*.vercel.app` preview hosts. Turn that off if previews should not call production.

The MCP container receives `MCP_PORT` and, when you add a real adapter later, whatever token that adapter's schema requires. The API reaches it with `MCP_SERVER_URL` (include the `/mcp` path) and optional `MCP_SERVER_TOKEN`. This repository does not ship a real OEM URL. Configuring `OEM_API_BASE_URL` without `OEM_API_SCHEMA_VERSION` makes the live adapter refuse the call.

## Containers

```bash
docker build -f backend/Dockerfile -t manualmind-api .
docker build -f mcp_servers/Dockerfile -t manualmind-mcp .
```

API command: `uvicorn app.main:app --host 0.0.0.0 --port 8091`

Worker command, same image: `python -m app.worker`

MCP command: `python -m manufacturer`

Put the API behind managed HTTPS. Logs are JSON on stdout with secret redaction. Health checks:

```bash
curl -fsS https://api.example.com/api/health
curl -fsS https://api.example.com/api/ready
```

## Postgres

Use a managed Postgres 16 service that offers the `vector` extension and TLS. A pooled connection string belongs in `DATABASE_URL`. Keep the pool small (`DB_POOL_SIZE` around 5) because the platform pooler already multiplexes clients. The API also opens a psycopg connection for LangGraph's `AsyncPostgresSaver`, so size the pooler for that extra session.

On a new database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

`infra/postgres/init.sql` does the same for the Compose cluster. Repeatable schema changes:

```bash
cd backend
DATABASE_URL='postgresql+psycopg://...' alembic upgrade head
```

Run that as a release step before shifting traffic. The migration creates the HNSW cosine index on `document_chunks.embedding`, foreign keys, and the ingestion, chat, trace, and evaluation tables. The column is `vector(1536)`. `EMBEDDING_DIMENSIONS` must stay 1536 or `/api/ready` fails.

Chat sessions, messages, retrieval runs, MCP audits, evaluation rows, and LangGraph checkpoints are in Postgres. Ingestion jobs are claimed with `FOR UPDATE SKIP LOCKED`. The UI polls document status. Do not rely on process memory for any of that.

## Object storage

Set all four `OBJECT_STORAGE_*` variables. The API uses them through boto3 (path-style endpoint). Local `STORAGE_LOCAL_PATH` is only for `APP_ENV` other than production. Vercel's filesystem is ephemeral and is not a document store.

## GitHub and Vercel

1. Push this repository to GitHub.
2. In Vercel, import that repository.
3. Set the project root directory to `frontend/`. Framework preset is Vite. Output is `dist`. `frontend/vercel.json` rewrites unknown paths to `index.html`, so a refresh on `/chat`, `/documents`, `/integrations`, `/evaluations`, or `/traces` stays in the app.
4. Set `VITE_API_BASE_URL` for Production and Preview. Preview can point at a staging API whose `CORS_ALLOWED_ORIGINS` includes that preview origin, or leave `CORS_ALLOW_VERCEL_PREVIEWS` on.
5. Leave the API, MCP server, worker, and Postgres off this Vercel project. When a second Vercel project serves the API, follow [VERCEL_CONNECTION.md](VERCEL_CONNECTION.md). Point `VITE_API_BASE_URL` at that API origin only after `GET /api/health` returns 200, then redeploy the UI.

GitHub Actions (`.github/workflows/ci.yml`) runs backend ruff and pytest, an evaluation smoke (`unsafe_answer_rate` must stay 0 on the smoke cases), and frontend lint, typecheck, test, and build. Let those pass before production.

### Vercel CLI

From `frontend/`, after `npm ci`:

```bash
npx vercel login
npx vercel link
npx vercel env add VITE_API_BASE_URL production
npx vercel env add VITE_API_BASE_URL preview
npx vercel deploy
npx vercel --prod
```

`vercel deploy` is a preview. `vercel --prod` updates production. Both build only the static UI. They do not migrate Postgres or start MCP.

## Streaming

`POST /api/chat/stream` is Server-Sent Events (`event: status|token|session|result|error|done`, plus `: keepalive` comments). The browser sends `X-Tenant-Id` and `X-User-Id`, and the session token in the JSON body for later turns. Conversation reads send `Authorization: Bearer <session_token>`. Stop generation aborts the fetch. If the socket drops after a session id was issued, the UI reloads messages with that bearer token. If nothing was saved, it shows the error and a retry.

## What was not deployed from this workspace

Deployment is real only after the commands above succeed against your accounts. A missing `VERCEL_TOKEN`, a missing managed Postgres URL, or a missing object-storage bucket means the public URL does not exist yet. Do not treat a local `vite` server as production.
