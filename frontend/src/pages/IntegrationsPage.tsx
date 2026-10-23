import { useEffect, useState } from "react"

import { Badge, Button, Panel } from "../components/ui.tsx"
import { listManufacturers, listMcpTools } from "../lib/api.ts"

export function IntegrationsPage() {
  const [adapters, setAdapters] = useState<Array<Record<string, unknown>>>([])
  const [tools, setTools] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)

  async function loadTools() {
    setChecking(true)
    try {
      setTools(await listMcpTools())
      setError("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Health check failed")
      setTools(null)
    } finally {
      setChecking(false)
    }
  }

  useEffect(() => {
    listManufacturers()
      .then((payload) => setAdapters(payload.manufacturers))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
    void loadTools()
  }, [])

  const catalog = Array.isArray(tools?.tools) ? (tools?.tools as Array<Record<string, unknown>>) : []

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">MCP integrations</h1>
        <p className="mt-1 max-w-3xl text-sm text-stone-600">
          Rainer and Acme Industrial are hypothetical adapters. Tools are read-only. A live OEM call is refused until a vetted schema and credentials are supplied. No endpoint is invented.
        </p>
      </div>
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {loading && <p className="text-sm text-stone-500">Loading adapters…</p>}
      <div className="grid gap-3 lg:grid-cols-3">
        {adapters.map((adapter) => (
          <article key={String(adapter.id)} className="rounded-xl border border-stone-200 bg-white p-4">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-semibold">{String(adapter.manufacturer)}</h2>
              <Badge tone={adapter.mode === "mock" ? "amber" : "stone"}>{String(adapter.mode)}</Badge>
            </div>
            <p className="mt-2 text-sm text-stone-600">{String(adapter.description)}</p>
            <p className="mt-2 font-mono text-xs text-stone-500">{Array.isArray(adapter.models) ? adapter.models.join(", ") || "no models" : ""}</p>
            <p className="mt-2 text-xs text-stone-500">Live calls: {adapter.live ? "enabled" : "not used"}</p>
          </article>
        ))}
      </div>
      <Panel
        title="Allowlisted tools"
        action={
          <Button size="sm" variant="outline" onClick={() => void loadTools()} disabled={checking}>
            {checking ? "Checking…" : "Run health check"}
          </Button>
        }
      >
        {!tools && !error && <p className="text-sm text-stone-500">No tool catalog yet.</p>}
        {tools && (
          <div className="space-y-3 text-sm">
            <p>
              Server {String(tools.server_url || "")} · {tools.reachable ? "reachable" : "unreachable"} · last check {String(tools.checked_at || "")}
            </p>
            <p className="text-amber-900">Every successful demo call is a mock fixture. A failed call stays failed.</p>
            {catalog.length === 0 && <p>The server returned no tools. Confirm MCP_SERVER_URL and that the manufacturer server is running.</p>}
            <ul className="space-y-2">
              {catalog.map((tool) => (
                <li key={String(tool.name)} className="rounded-md border border-stone-200 px-3 py-2">
                  <span className="font-mono font-semibold">{String(tool.name)}</span>
                  <span className="ml-2 text-xs uppercase text-stone-500">{tool.read_only === false ? "not read-only" : "read-only"}</span>
                  <p className="text-stone-600">{String(tool.description || "")}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Panel>
    </div>
  )
}
