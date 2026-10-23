# ManualMind frontend

Vite + React UI for the factory manual assistant. The API is not part of this package.

```bash
cp .env.example .env
npm ci
npm run dev
```

`VITE_API_BASE_URL` is the only browser variable. Leave it empty for local dev. The Vite server proxies `/api` to the FastAPI process on port 8091, so the browser stays on the same origin. Set it to the public API origin only for a published build. See the repository README and `docs/DEPLOYMENT.md`.
