import { useEffect, useState } from "react"

import { Badge, Button, Panel } from "../components/ui.tsx"
import { getEvaluation, listEvaluations, runEvaluation } from "../lib/api.ts"
import type { EvalDetail, EvalRun } from "../lib/types.ts"

const SCORE_KEYS = [
  "recall_at_5",
  "mrr_at_10",
  "citation_precision",
  "faithfulness",
  "relevance",
  "correctness",
  "tool_selection",
  "decision_accuracy",
  "route_accuracy",
  "conflict_explained",
  "unsafe_answer_rate",
  "latency_p50_ms",
  "latency_p95_ms",
]

export function EvaluationsPage() {
  const [runs, setRuns] = useState<EvalRun[]>([])
  const [note, setNote] = useState("")
  const [size, setSize] = useState(0)
  const [leftId, setLeftId] = useState("")
  const [rightId, setRightId] = useState("")
  const [left, setLeft] = useState<EvalDetail | null>(null)
  const [right, setRight] = useState<EvalDetail | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)

  async function refresh() {
    const payload = await listEvaluations()
    setRuns(payload.runs)
    setNote(payload.judge_note)
    setSize(payload.dataset_size)
    setLeftId((current) => current || payload.runs[0]?.id || "")
    setRightId((current) => current || payload.runs[1]?.id || payload.runs[0]?.id || "")
  }

  useEffect(() => {
    refresh()
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!leftId) return
    getEvaluation(leftId).then(setLeft).catch((err: Error) => setError(err.message))
  }, [leftId])

  useEffect(() => {
    if (!rightId) return
    getEvaluation(rightId).then(setRight).catch((err: Error) => setError(err.message))
  }, [rightId])

  const guardrailCases = (left?.results || []).filter((item) =>
    ["prompt_injection", "unsafe_operation", "mcp_timeout"].includes(item.category),
  )

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Evaluations</h1>
          <p className="mt-1 max-w-3xl text-sm text-stone-600">
            {size} labeled questions. {note || "Scores are deterministic checks. An LLM judge is not the source of truth."}
          </p>
        </div>
        <Button
          variant="signal"
          disabled={running}
          onClick={() => {
            setRunning(true)
            setError("")
            void runEvaluation()
              .then(async (detail) => {
                await refresh()
                setLeftId(detail.id)
                setLeft(detail)
              })
              .catch((err: Error) => setError(err.message))
              .finally(() => setRunning(false))
          }}
        >
          {running ? "Running…" : "Run evaluation"}
        </Button>
      </div>
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {loading && <p className="text-sm text-stone-500">Loading runs…</p>}
      {!loading && runs.length === 0 && <p className="text-sm text-stone-500">No runs yet. Start one to score retrieval, abstention, and unsafe-answer rate.</p>}
      {runs.length > 0 && (
        <div className="flex flex-wrap gap-3">
          <Select label="Scorecard" value={leftId} runs={runs} onChange={setLeftId} />
          <Select label="Compare with" value={rightId} runs={runs} onChange={setRightId} />
        </div>
      )}
      {left && (
        <Panel title="Scorecard">
          <Experiment experiment={left.experiment} />
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {SCORE_KEYS.map((key) => (
              <div key={key} className="rounded-md border border-stone-200 px-3 py-2">
                <p className="text-xs uppercase tracking-wide text-stone-500">{key.replaceAll("_", " ")}</p>
                <p className="text-lg font-semibold">{formatMetric(left.metrics[key])}</p>
                {right && right.id !== left.id && (
                  <p className="text-xs text-stone-500">other run {formatMetric(right.metrics[key])}</p>
                )}
              </div>
            ))}
          </div>
          {typeof left.metrics.score_note === "string" && <p className="mt-3 text-xs text-stone-600">{left.metrics.score_note}</p>}
        </Panel>
      )}
      {left && right && left.id !== right.id && (
        <Panel title="Experiment comparison">
          <div className="grid gap-4 md:grid-cols-2 text-sm">
            <Experiment experiment={left.experiment} />
            <Experiment experiment={right.experiment} />
          </div>
        </Panel>
      )}
      {!!guardrailCases.length && (
        <Panel title="Guardrail and failure cases">
          <ul className="space-y-2 text-sm">
            {guardrailCases.map((item) => (
              <li key={item.case_id} className="rounded-md border border-stone-200 px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">{item.case_id}</span>
                  <Badge tone={item.scores.unsafe_answer ? "red" : "green"}>{item.scores.unsafe_answer ? "unsafe answer" : "held"}</Badge>
                  <Badge>{item.category}</Badge>
                </div>
                <p className="mt-1">{item.question}</p>
                <p className="text-xs text-stone-500">
                  route {String(item.actual.route || "")} · action {String(item.actual.eval_action || "")}
                </p>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  )
}

function Select({ label, value, runs, onChange }: { label: string; value: string; runs: EvalRun[]; onChange: (value: string) => void }) {
  return (
    <label className="text-xs font-semibold uppercase tracking-wide text-stone-500">
      {label}
      <select className="mt-1 block h-9 rounded-md border border-stone-300 bg-white px-2 text-sm font-normal" value={value} onChange={(event) => onChange(event.target.value)}>
        {runs.map((run) => (
          <option key={run.id} value={run.id}>
            {run.started_at?.slice(0, 19) || run.id.slice(0, 8)} · {String(run.experiment.model || run.status)}
          </option>
        ))}
      </select>
    </label>
  )
}

function Experiment({ experiment }: { experiment: Record<string, unknown> }) {
  return (
    <dl className="grid grid-cols-2 gap-1 text-xs text-stone-600">
      {Object.entries(experiment).map(([key, value]) => (
        <div key={key}>
          <dt className="uppercase tracking-wide text-stone-400">{key}</dt>
          <dd className="font-medium text-stone-800">{String(value)}</dd>
        </div>
      ))}
    </dl>
  )
}

function formatMetric(value: unknown) {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3)
  if (value === null || value === undefined) return "—"
  return String(value)
}
