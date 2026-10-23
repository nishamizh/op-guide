# Spec: connect the Vercel UI to the Vercel API

Status: the two projects exist. The UI is served. The API project does not answer yet, so the connection is not complete.

This file is the contract for wiring those two Vercel projects. Host split, containers, and Postgres setup stay in [DEPLOYMENT.md](DEPLOYMENT.md).

Recorded from team `nisha` (`nisha-a8f0`, `team_CRkxiRz0JOckMsT9neOroq5I`) on 23 October 2026.

## 1. Projects

Vercel does not join these projects. The browser on the UI origin calls the API origin.

| | UI | API |
| --- | --- | --- |
| Vercel project | `op-guide-lw4a` | `op-guide` |
| Project id | `prj_wY5gEt3rEDPAJL8waXzzWOySJus6` | `prj_GIpxN9wixAHFmpq3XuDkPpvuO7LY` |
| Framework | Vite | FastAPI |
| Root directory | `frontend/` | `backend/` once the function can import `app.main:app` |
| Production origin | `https://op-guide-lw4a.vercel.app` | `https://op-guide.vercel.app` |
| Dashboard | [op-guide-lw4a](https://vercel.com/nisha-a8f0/op-guide-lw4a) | [op-guide](https://vercel.com/nisha-a8f0/op-guide) |

The MCP server is a third process. It is not either Vercel project. The API reaches it with `MCP_SERVER_URL`.

## 2. Connection rule

The UI builds with one public API origin:

```
VITE_API_BASE_URL=https://op-guide.vercel.app
```

Requirements:

1. Scheme `https`, no path, no trailing slash. The client appends `/api/...` itself.
2. Set it on **op-guide-lw4a** for Production and Preview.
3. Redeploy **op-guide-lw4a** after every change. Vite copies `VITE_API_BASE_URL` into the JavaScript bundle. Saving the variable does not change a build that already finished.
4. A loopback value (`http://127.0.0.1:8091` or `http://localhost:8091`) is ignored when the page is not served from that same origin. The published page must not depend on the visitor's computer.
5. `VITE_API_BASE_URL` is the only `VITE_` variable this app reads. Database URLs, `SESSION_SECRET`, `OPENAI_API_KEY`, and object-storage keys stay on **op-guide**.

Local `npm run dev` leaves `VITE_API_BASE_URL` empty. The Vite server proxies `/api` to `127.0.0.1:8091`.

## 3. Browser request

Every API call from the page is cross-origin.

| Item | Value |
| --- | --- |
| Methods | `GET`, `POST`, `DELETE`, `OPTIONS` |
| Credentials | included |
| Scope headers | `X-Tenant-Id` (default `demo`), `X-User-Id` (default `operator`) |
| Body header | `Content-Type: application/json`, except multipart upload |
| Conversation reads | `Authorization: Bearer <session_token>` |
| Chat stream | `POST /api/chat/stream`, `Accept: text/event-stream` |

The API allows those headers and echoes the request origin when it matches `CORS_ALLOWED_ORIGINS` or, while `CORS_ALLOW_VERCEL_PREVIEWS=true`, `https://*.vercel.app`. Credentials are on, so `Access-Control-Allow-Origin` is never `*`.

On **op-guide**, set the exact UI origin:

```
CORS_ALLOWED_ORIGINS=https://op-guide-lw4a.vercel.app
CORS_ALLOW_VERCEL_PREVIEWS=true
```

Preview deployments of the UI use a different `*.vercel.app` host. The preview flag covers those hosts. Turn it off only when previews must not call this API.

## 4. API project must answer before the UI is pointed at it

Do not set the UI to `https://op-guide.vercel.app` until this returns 200:

```bash
curl -fsS https://op-guide.vercel.app/api/health
```

Expected body: `{"status":"ok","service":"manualmind-api"}`.

Observed on 23 October 2026, about 11:03 AM Pacific: that URL returns HTTP 500 with `x-vercel-error: FUNCTION_INVOCATION_FAILED`. The deployment `dpl_618DcZWUab5xWCqZ91DdJaCBWc9w` is READY, and the build entrypoint is the repository root. The ASGI app is `app` in `backend/app/main.py`. There is no root `app.py`. Neon has already injected `DATABASE_URL` and the other `POSTGRES_*` variables into **op-guide**. The function still exits before it serves `/api/health`.

Until that health check is 200, leave the UI on a host that actually serves the API. Pointing the UI at the 500 replaces "Failed to fetch" with a server error.

### 4.1 API settings required for a production boot

`APP_ENV=production` refuses to start until `production_problems()` is empty. Set these on **op-guide**, not on the UI:

| Variable | Requirement |
| --- | --- |
| `APP_ENV` | `production` |
| `DATABASE_URL` | Managed Postgres, TLS, `vector` installed. Neon already supplies this on **op-guide**. Use a driver URL the app can open (`postgresql+psycopg://...`) and keep `EMBEDDING_DIMENSIONS=1536`. |
| `DB_SSLMODE` | `require`, `verify-ca`, or `verify-full` |
| `SESSION_SECRET` | Secret store value. Not `dev-only-change-me`. |
| `CORS_ALLOWED_ORIGINS` | `https://op-guide-lw4a.vercel.app` |
| `MCP_SERVER_URL` | Public MCP origin including the `/mcp` path. Not `127.0.0.1`. |
| `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_ACCESS_KEY`, `OBJECT_STORAGE_SECRET_KEY` | S3-compatible store. Vercel disk is not the document store. |
| `AUTO_MIGRATE` | `false` in production. Run `alembic upgrade head` as a release step. |
| `EMBED_WORKER` | `false` on the web function if a separate worker runs `python -m app.worker`. |
| `SEED_DEMO_DATA` | `false` in production unless a demo seed is intentional. |

`GET /api/ready` stays 503 until the database, pgvector column, object storage, CORS, session secret, and MCP URL pass those checks.

The default MCP URL inside the code is `http://127.0.0.1:8092/mcp`. That address does not exist in the API function. Chat that needs a manufacturer tool waits on that URL until `MCP_SERVER_URL` is a reachable server.

## 5. UI build

**op-guide-lw4a** uses `frontend/vercel.json`:

- Framework Vite, output `dist`.
- Install and build: `npm run build` (`tsc -b && vite build`).
- Rewrite `/(.*)` to `/index.html`, so `/chat`, `/documents`, `/integrations`, `/evaluations`, and `/traces` survive refresh.

That rewrite is for the UI project. It must not be how `/api` is served. API routes belong on `https://op-guide.vercel.app`.

`frontend/api/[...path].js` is an optional same-origin proxy. It forwards to `API_UPSTREAM` or `VITE_API_BASE_URL` and refuses a loopback target. The primary connection in this spec is the browser calling **op-guide** directly, not this proxy.

## 6. Acceptance

The connection is done only when all of these are true on the production aliases.

1. `curl -fsS https://op-guide.vercel.app/api/health` prints the health JSON.
2. `curl -fsS https://op-guide.vercel.app/api/ready` is 200, or the body lists the remaining production gaps on purpose.
3. A preflight from the UI origin succeeds:

   ```bash
   curl -sS -D - -o /dev/null -X OPTIONS https://op-guide.vercel.app/api/documents \
     -H 'Origin: https://op-guide-lw4a.vercel.app' \
     -H 'Access-Control-Request-Method: GET' \
     -H 'Access-Control-Request-Headers: x-tenant-id,x-user-id,content-type'
   ```

   The response includes `access-control-allow-origin: https://op-guide-lw4a.vercel.app` and `access-control-allow-credentials: true`.

4. The UI bundle for `https://op-guide-lw4a.vercel.app` contains `https://op-guide.vercel.app` and does not contain `127.0.0.1:8091`.
5. Opening `https://op-guide-lw4a.vercel.app/documents` lists manuals, or an empty knowledge base, without "Failed to fetch".
6. A chat turn on `https://op-guide-lw4a.vercel.app/chat` receives SSE events `session`, `status`, and `done` from `https://op-guide.vercel.app/api/chat/stream`.
7. Deployment-specific hostnames (`*-nisha-a8f0.vercel.app` with the deployment hash) may redirect to Vercel SSO. Use the public aliases above for the browser check. SSO protection on this team is `all_except_custom_domains`.

## 7. What not to do

- Do not treat a READY deployment as a working API. **op-guide** is READY and still returns 500.
- Do not put `DATABASE_URL` or other Neon variables into a `VITE_` name. Those values would ship in the browser bundle.
- Do not store uploads on the Vercel function disk.
- Do not expect the two projects to share memory, files, or `localhost`.
- Do not point `VITE_API_BASE_URL` at `https://op-guide.vercel.app` while section 4's health check fails.
