import { RefreshCw, Trash2 } from "lucide-react"
import { useCallback, useEffect, useState, type FormEvent } from "react"
import { useParams } from "react-router-dom"

import { Badge, Button, Panel } from "../components/ui.tsx"
import { deleteDocument, getDocument, listDocuments, reindexDocument, uploadDocument } from "../lib/api.ts"
import type { DocumentRow, IndexStats } from "../lib/types.ts"

const STAGES = ["upload", "parse", "chunk", "embed", "indexed"]

const emptyForm = {
  title: "",
  manufacturer: "Rainer",
  machine_model: "R200",
  document_revision: "C",
  equipment_type: "CNC milling machine",
  plant: "North Demo Plant",
  effective_date: "2026-01-15",
}

export function DocumentsPage() {
  const { documentId } = useParams()
  const [documents, setDocuments] = useState<DocumentRow[]>([])
  const [stats, setStats] = useState<IndexStats | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [detail, setDetail] = useState<DocumentRow | null>(null)

  const load = useCallback(async () => {
    const payload = await listDocuments()
    setDocuments(payload.documents)
    setStats(payload.stats)
    setLoading(false)
  }, [])

  useEffect(() => {
    load().catch((err: Error) => {
      setError(err.message)
      setLoading(false)
    })
  }, [load])

  useEffect(() => {
    if (!documents.some((item) => item.status !== "indexed" && item.status !== "failed")) return
    const timer = window.setInterval(() => {
      load().catch((err: Error) => setError(err.message))
    }, 2000)
    return () => window.clearInterval(timer)
  }, [documents, load])

  useEffect(() => {
    if (!documentId) {
      setDetail(null)
      return
    }
    getDocument(documentId)
      .then(setDetail)
      .catch((err: Error) => setError(err.message))
  }, [documentId, documents])

  async function onUpload(event: FormEvent) {
    event.preventDefault()
    if (!file) {
      setError("Choose a PDF, DOCX, TXT, or Markdown file.")
      return
    }
    const body = new FormData()
    body.append("file", file)
    for (const [key, value] of Object.entries(form)) body.append(key, value)
    setError("")
    try {
      await uploadDocument(body)
      setFile(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed")
    }
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-semibold">Knowledge base</h1>
        <p className="mt-1 max-w-3xl text-sm text-stone-600">
          Uploads are stored, parsed into pages and sections, chunked, embedded, and added to the BM25 index. Demo manuals are marked and can be removed.
        </p>
      </div>
      {stats && (
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Documents" value={String(stats.documents)} />
          <Stat label="Indexed" value={String(stats.indexed)} />
          <Stat label="Chunks" value={String(stats.chunks)} />
          <Stat label="Demo files" value={String(stats.demo_documents)} />
          <Stat label="Index revision" value={String(stats.index_revision)} />
          <Stat label="Embeddings" value={stats.embedding_model || "pending"} />
        </div>
      )}
      <Panel title="Upload a manual">
        <form className="grid gap-3 md:grid-cols-2" onSubmit={(event) => void onUpload(event)}>
          <Field label="Title" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
          <Field label="Manufacturer" value={form.manufacturer} onChange={(value) => setForm({ ...form, manufacturer: value })} />
          <Field label="Model" value={form.machine_model} onChange={(value) => setForm({ ...form, machine_model: value })} />
          <Field label="Revision" value={form.document_revision} onChange={(value) => setForm({ ...form, document_revision: value })} />
          <Field label="Equipment type" value={form.equipment_type} onChange={(value) => setForm({ ...form, equipment_type: value })} />
          <Field label="Plant" value={form.plant} onChange={(value) => setForm({ ...form, plant: value })} />
          <Field label="Effective date" value={form.effective_date} onChange={(value) => setForm({ ...form, effective_date: value })} />
          <label className="text-xs font-semibold uppercase tracking-wide text-stone-500">
            File
            <input
              className="mt-1 block w-full text-sm font-normal normal-case"
              type="file"
              accept=".pdf,.docx,.txt,.md,.markdown"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
            />
          </label>
          <div className="md:col-span-2">
            <Button type="submit" variant="signal">
              Upload and index
            </Button>
          </div>
        </form>
      </Panel>
      {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
      {loading && <p className="text-sm text-stone-500">Loading manuals…</p>}
      {!loading && documents.length === 0 && <p className="text-sm text-stone-500">No manuals in this tenant. Upload one or start the API with demo seeding enabled.</p>}
      <div className="space-y-3">
        {documents.map((document) => (
          <article key={document.id} id={document.id} className="rounded-xl border border-stone-200 bg-white p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="font-semibold">{document.title}</h2>
                <p className="text-sm text-stone-600">
                  {document.manufacturer} {document.machine_model} · rev {document.document_revision} · {document.plant} · {document.chunk_count} chunks
                </p>
              </div>
              <div className="flex gap-2">
                {document.is_demo && <Badge tone="amber">demo</Badge>}
                <Badge tone={document.status === "indexed" ? "green" : document.status === "failed" ? "red" : "stone"}>{document.status}</Badge>
              </div>
            </div>
            <ol className="mt-3 flex flex-wrap gap-2 text-xs">
              {STAGES.map((stage) => {
                const current = document.job?.stage || document.status
                const index = STAGES.indexOf(current)
                const reached = STAGES.indexOf(stage) <= index || document.status === "indexed"
                return (
                  <li key={stage} className={`rounded-full px-2 py-1 ${reached ? "bg-lime-100 text-lime-950" : "bg-stone-100 text-stone-500"}`}>
                    {stage}
                  </li>
                )
              })}
            </ol>
            {document.job?.error && <p className="mt-2 text-sm text-red-700">{document.job.error}</p>}
            <div className="mt-3 flex gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  void reindexDocument(document.id).then(load).catch((err: Error) => setError(err.message))
                }}
              >
                <RefreshCw className="h-3 w-3" /> Reindex
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  void deleteDocument(document.id).then(load).catch((err: Error) => setError(err.message))
                }}
              >
                <Trash2 className="h-3 w-3" /> Delete
              </Button>
            </div>
          </article>
        ))}
      </div>
      {detail && (
        <Panel title={`Sections in ${detail.title}`}>
          <ul className="space-y-3">
            {(detail.chunks || []).map((chunk) => (
              <li key={chunk.id} className="rounded-md border border-stone-200 p-3 text-sm">
                <p className="font-semibold">
                  {chunk.section_title} · {chunk.section_id} · page {chunk.page_start}
                  {chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ""} · rev {chunk.revision} · {chunk.token_count} tokens
                </p>
                {chunk.injection_suspected && <p className="text-xs text-red-700">This passage was flagged as instruction-like and is excluded from answers.</p>}
                <p className="mt-1 text-stone-600">{chunk.preview}</p>
                <p className="mt-1 font-mono text-xs text-stone-400">{chunk.id}</p>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-stone-500">{label}</p>
      <p className="truncate text-sm font-semibold">{value}</p>
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs font-semibold uppercase tracking-wide text-stone-500">
      {label}
      <input className="mt-1 block h-9 w-full rounded-md border border-stone-300 px-2 text-sm font-normal normal-case" value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  )
}
