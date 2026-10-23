# ManualMind

ManualMind answers troubleshooting questions from fictional industrial manuals. An operator asks about a machine. A LangGraph supervisor chooses manual retrieval, a read-only manufacturer tool, both, a clarifying question, or a refusal. Answers cite stored document ids, pages, sections, and revisions. Rainer and Acme Industrial are demo manufacturers. Their tool payloads are mock fixtures, not live telemetry.

## Layout

- `frontend/` React chat, knowledge base, MCP status, evaluations, and traces. This is the Vercel project.
- `backend/` FastAPI, ingestion, pgvector, BM25, LangGraph, and evaluations.
- `mcp_servers/` read-only Model Context Protocol server for the demo adapters.
- `infra/postgres/` enables pgvector on a fresh cluster.
- `docs/DEPLOYMENT.md` is the production split: Vercel for the UI, a Python host for the API and MCP server, managed Postgres for data.
- `docs/VERCEL_CONNECTION.md` is the spec for pointing the Vercel UI project at the Vercel API project.

Do not run Postgres or the MCP server inside a Vercel serverless function. Both are long-lived processes.

## Setup

Requirements: Python 3.12, Node 22, and PostgreSQL 16 with the `vector` extension.

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm ci && cd ..
cp .env.example .env
cp frontend/.env.example frontend/.env
```

Create the database once:

```bash
sudo -u postgres psql -c "CREATE USER manualmind WITH PASSWORD 'manualmind';" || true
sudo -u postgres psql -c "CREATE DATABASE manualmind OWNER manualmind;" || true
sudo -u postgres psql -d manualmind -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

One-command start after Postgres is up:

```bash
make dev
```

That starts the MCP server on port 8092, the API on port 8091, and the web app on port 4178. The API applies Alembic migrations and seeds the demo manuals on startup when `SEED_DEMO_DATA=true`.

Docker Compose is the other one-command path. It builds the API, the worker, the MCP server, and Postgres:

```bash
docker compose up --build
cd frontend && npm run dev
```

Open [http://127.0.0.1:4178](http://127.0.0.1:4178).

`OPENAI_API_KEY` is optional. With it empty, embeddings are local hashed n-grams labeled `local-hashed-ngram` and answers use a template synthesizer. Those vectors are not OpenAI semantic embeddings and are not probabilities. Set the key to use `text-embedding-3-small` and `gpt-4o-mini`.

## Sample question

Ask: `What does Rainer R200 E104 mean?`

The reply should say coolant flow is below the Revision C trip of 1.5 bar, cite section `r200-e104` with a real document id and page, and include a DEMO MOCK `get_error_code` result. It must not present that fixture as plant telemetry.

Other prompts on the chat page:

- Why is the coolant pressure low and what approved checks can a technician perform?
- Check Rainer R200 current status and compare with the manual.
- Which manual revision supports your response?
- What if no document or manufacturer tool supports my question?

A request to bypass an interlock or disable a guard is refused. The assistant does not start, stop, or modify equipment.

## How retrieval works

1. Upload or seed a manual. The worker parses PDF, DOCX, TXT, or Markdown into pages, sections, and pipe tables.
2. Chunks target 500–800 cl100k tokens with a 100-token overlap. Each chunk keeps the section id, page, revision, and document id that were parsed. Citations use those stored ids.
3. Each chunk is embedded (OpenAI when a key is set, otherwise the labeled local hash) into `document_chunks.embedding vector(1536)`.
4. A query embeds the same way. pgvector returns cosine top 12. `1 - cosine_distance` is recorded as similarity and is not treated as a probability.
5. An in-process Okapi BM25 index over the same chunks returns top 12. It rebuilds when `app_meta.index_revision` changes. A generated `tsvector` and GIN index are also stored.
6. Reciprocal rank fusion combines the lists with `weight / (60 + rank)`. Weights default to 1 and 1.
7. A heuristic rerank orders the fused pool and returns about 6 chunks, keeping a conflicting older revision visible instead of dropping it.
8. Confidence is a weighted heuristic of retrieval relevance, source quality, coverage, consistency, and groundedness. Bands high ≥ 0.80 and medium ≥ 0.60 are illustrative until you calibrate them on labeled data.

## How MCP works

The manufacturer server uses the official MCP Python SDK (`MCPServer`, streamable HTTP, path `/mcp`). Tools:

- `get_machine_information(manufacturer, model)`
- `get_error_code(manufacturer, model, error_code)`
- `get_maintenance_history(machine_id)`
- `get_operating_limits(model)`
- `get_machine_status(machine_id)`

All five are read-only. The API discovers the catalog, then calls only that allowlist, with a deadline, sanitized arguments, and an audit row. A timeout or error is stored as a failed call. The answer is not allowed to claim the tool succeeded. Demo machine ids are `R200-DEMO-01`, `R500-DEMO-01`, and `P300-DEMO-01`.

`OEM_API_BASE_URL` without a vetted `OEM_API_SCHEMA_VERSION` does not invent an endpoint. The live adapter stays refused.

## curl

```bash
curl -s http://127.0.0.1:8091/api/health
curl -s http://127.0.0.1:8091/api/ready
curl -s http://127.0.0.1:8091/api/documents -H 'X-Tenant-Id: demo' -H 'X-User-Id: operator'
curl -s http://127.0.0.1:8091/api/mcp/tools -H 'X-Tenant-Id: demo' -H 'X-User-Id: operator'
curl -N -s http://127.0.0.1:8091/api/chat/stream \
  -H 'Content-Type: application/json' \
  -H 'X-Tenant-Id: demo' \
  -H 'X-User-Id: operator' \
  -d '{"message":"What does Rainer R200 E104 mean?","manufacturer":"Rainer","machine_model":"R200"}'
```

OpenAPI is served at `http://127.0.0.1:8091/docs`.

Chat reads for a saved conversation need `Authorization: Bearer <session_token>` from the chat response. Uploads are `multipart/form-data` on `POST /api/documents/upload` with `title`, `manufacturer`, `machine_model`, `document_revision`, `equipment_type`, `plant`, and `effective_date`.

## Tests and evaluation

```bash
make test
make eval
```

Backend tests mock OpenAI by leaving the key empty. They cover RRF, BM25, chunk bounds, guardrails, upload isolation, an end-to-end E104 answer with a mock MCP call, and an evaluation smoke set.

`python -m app.evals` runs the 24 labeled questions and prints recall@5, MRR@10, citation precision, faithfulness, relevance, correctness, tool selection, escalation accuracy, unsafe-answer rate, latency percentiles, token usage, and estimated cost. The experiment block records model, prompt version, embedding model, and index revision. `llm_judge` is false. Those scores are checks against labeled facts and section ids, not an LLM judge.

A live OpenAI check, only when `OPENAI_API_KEY` is set:

```bash
backend/.venv/bin/python -m app.scripts.live_openai
```

The script embeds one seeded E104 chunk and asks for one grounded completion. If the key is missing it exits 2 and does not pretend the call happened.

## Limitations

- Demo manuals and mock tool payloads are fictional. They are labeled DEMO and must not be used on real machinery.
- Hashed n-gram vectors are a lexical fallback. They are a different vector space from `text-embedding-3-small`. Reindex after you set an API key.
- The reranker is a logged weighted heuristic, not a neural cross-encoder.
- Confidence bands are not calibrated.
- There is no autonomous control, no interlock bypass, and no remote start or stop.
- Retrieved pages and tool JSON are untrusted data. They are not system instructions.
- Local development stores files on `STORAGE_LOCAL_PATH`. Production must use S3-compatible object storage. See `docs/DEPLOYMENT.md`.

## Deployment sketch

| Piece | Where |
| --- | --- |
| React UI | Vercel, root directory `frontend/` |
| FastAPI and the ingestion worker | A persistent Python 3.12 host or container |
| MCP server | That same kind of host, reached via `MCP_SERVER_URL` |
| Postgres + pgvector | Managed Postgres with TLS |
| Manual files | S3-compatible object storage |

Commands, CORS, GitHub connection, and the Vercel CLI are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). The two-project wiring spec is [docs/VERCEL_CONNECTION.md](docs/VERCEL_CONNECTION.md).
