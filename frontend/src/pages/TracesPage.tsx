import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"

import { Badge, Panel } from "../components/ui.tsx"
import { getTrace, listTraces } from "../lib/api.ts"
import type { TraceDetail, TraceSummary } from "../lib/types.ts"

export function TracesPage() {
  const { messageId } = useParams()
  const [traces, setTraces] = useState<TraceSummary[]>([])
  const [detail, setDetail] = useState<TraceDetail | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listTraces()
      .then((payload) => setTraces(payload.traces))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    const id = messageId || traces[0]?.message_id
    if (!id) return
    getTrace(id)
      .then(setDetail)
      .catch((err: Error) => setError(err.message))
  }, [messageId, traces])

  const nodes = detail?.run?.trace || []
  const route = detail?.run?.route || detail?.message.route

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Architecture and trace</h1>
        <p className="mt-1 max-w-3xl text-sm text-stone-600">
          Each answer records which agents ran, whether retrieval and MCP ran, how evidence was ranked, and what the guardrails decided. Similarity numbers are heuristics.
        </p>
      </div>
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {loading && <p className="text-sm text-stone-500">Loading traces…</p>}
      {!loading && traces.length === 0 && <p className="text-sm text-stone-500">No traces yet. Ask a question on the chat page first.</p>}
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <aside className="max-h-[70vh] space-y-1 overflow-auto">
          {traces.map((trace) => (
            <Link
              key={trace.message_id}
              to={`/traces/${trace.message_id}`}
              className={`block rounded-md border px-3 py-2 text-sm ${detail?.message.id === trace.message_id ? "border-stone-800 bg-white" : "border-transparent bg-white/60"}`}
            >
              <span className="line-clamp-2">{trace.preview}</span>
              <span className="mt-1 block text-xs text-stone-500">
                {trace.route} · {trace.confidence_label || "n/a"}
              </span>
            </Link>
          ))}
        </aside>
        {detail && (
          <div className="space-y-3">
            <Panel title="Decision">
              <div className="flex flex-wrap gap-2">
                <Badge tone="amber">{route || "unknown"}</Badge>
                <Badge>{detail.message.confidence_label || "no label"}</Badge>
                {detail.run?.embedding_model && <Badge tone="stone">{detail.run.embedding_model}</Badge>}
              </div>
              <p className="mt-3 text-sm text-stone-600">
                Vector space {detail.run?.vector_space || "n/a"} · index revision {detail.run?.index_revision ?? "n/a"} · retrieval attempt {detail.run?.attempt ?? "n/a"} ·{" "}
                {detail.run?.latency_ms ?? "n/a"} ms
              </p>
              <p className="mt-2 text-sm">{detail.run?.rewritten_query || detail.run?.query}</p>
            </Panel>
            <Panel title="Agents">
              {nodes.length === 0 && <p className="text-sm text-stone-500">This message has no retrieval trace.</p>}
              <ol className="space-y-2">
                {nodes.map((node, index) => (
                  <li key={`${node.node}-${index}`} className="flex items-start justify-between gap-3 rounded-md border border-stone-200 px-3 py-2 text-sm">
                    <span>
                      <span className="font-mono">{node.node}</span>
                      <span className="ml-2 text-xs uppercase text-stone-500">{node.status}</span>
                    </span>
                    <span className="font-mono text-xs">{node.duration_ms} ms</span>
                  </li>
                ))}
              </ol>
            </Panel>
            <Panel title="Evidence ranking">
              <ul className="space-y-2 text-sm">
                {detail.evidence.map((item, index) => (
                  <li key={String(item.chunk_id || index)} className="rounded-md border border-stone-200 px-3 py-2">
                    <p className="font-semibold">
                      #{String(item.rank)} {String(item.section_title || item.section_id)} · rev {String(item.revision || "")} · page {String(item.page_start || "")}
                    </p>
                    <p className="text-xs text-stone-500">
                      rerank {String(item.rerank_score)} · bm25 rank {String(item.bm25_rank)} · vector rank {String(item.vector_rank)} · cosine {String(item.vector_similarity)}
                      {item.excluded ? ` · excluded (${String(item.exclude_reason)})` : ""}
                    </p>
                    <p className="mt-1 text-stone-700">{String(item.snippet || "")}</p>
                  </li>
                ))}
              </ul>
            </Panel>
            <Panel title="MCP calls">
              {detail.mcp_calls.length === 0 && <p className="text-sm text-stone-500">This turn did not call a manufacturer tool.</p>}
              <ul className="space-y-2 text-sm">
                {detail.mcp_calls.map((call, index) => (
                  <li key={`${String(call.tool_name)}-${index}`} className="rounded-md border border-stone-200 px-3 py-2">
                    <div className="flex flex-wrap gap-2">
                      <span className="font-mono">{String(call.tool_name)}</span>
                      <Badge tone={call.status === "ok" ? "green" : "red"}>{String(call.status)}</Badge>
                      {call.is_mock ? <Badge tone="amber">mock</Badge> : null}
                    </div>
                    {call.error ? <p className="mt-1 text-red-700">{String(call.error)}</p> : null}
                    <pre className="mt-2 overflow-auto whitespace-pre-wrap font-mono text-xs text-stone-600">{JSON.stringify(call.result ?? call.arguments, null, 2)}</pre>
                  </li>
                ))}
              </ul>
            </Panel>
            <Panel title="Guardrails">
              <ul className="space-y-1 text-sm">
                {(detail.message.warnings || []).map((warning) => (
                  <li key={warning.code + warning.message}>
                    {warning.code}: {warning.message}
                  </li>
                ))}
                {!detail.message.warnings?.length && <li className="text-stone-500">No guardrail warnings on the final answer.</li>}
              </ul>
            </Panel>
          </div>
        )}
      </div>
    </div>
  )
}
