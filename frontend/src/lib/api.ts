import type {
  ChatMessage,
  Conversation,
  DocumentRow,
  EvalDetail,
  EvalRun,
  IndexStats,
  TraceDetail,
  TraceSummary,
} from "./types.ts"

const STORAGE_TENANT = "manualmind-tenant"
const STORAGE_USER = "manualmind-user"

function loopback(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "[::1]"
}

/** Origin the browser should call. Empty means the page's own origin. */
export function resolveApiBase(configured: string | undefined, pageOrigin?: string): string {
  const value = (configured ?? "").trim().replace(/\/$/, "")
  if (!value || !pageOrigin) return value
  try {
    const api = new URL(value)
    const page = new URL(pageOrigin)
    // 127.0.0.1 in the bundle is this machine, not the visitor's. A forwarded
    // dev server and the published site must stay on the origin that served the page.
    if (loopback(api.hostname) && api.origin !== page.origin) return ""
  } catch {
    return ""
  }
  return value
}

export function apiBase(): string {
  const pageOrigin = typeof window === "undefined" ? undefined : window.location.origin
  return resolveApiBase(import.meta.env.VITE_API_BASE_URL, pageOrigin)
}

export function scopeHeaders(): Record<string, string> {
  return {
    "X-Tenant-Id": localStorage.getItem(STORAGE_TENANT) || "demo",
    "X-User-Id": localStorage.getItem(STORAGE_USER) || "operator",
  }
}

export function setOperator(tenant: string, user: string) {
  localStorage.setItem(STORAGE_TENANT, tenant || "demo")
  localStorage.setItem(STORAGE_USER, user || "operator")
}

async function parseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { message?: string; detail?: unknown }
    if (body.message) return body.message
    if (typeof body.detail === "string") return body.detail
  } catch {
    /* response had no JSON body */
  }
  return `Request failed (${response.status})`
}

async function fetchApi(path: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(`${apiBase()}${path}`, init)
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err
    if (err instanceof Error && err.name === "AbortError") throw err
    const where = apiBase() || "this site"
    throw new Error(`Cannot reach the ManualMind API (${where}).`)
  }
}

export async function apiGet<T>(path: string, extra?: HeadersInit): Promise<T> {
  const response = await fetchApi(path, {
    headers: { ...scopeHeaders(), ...extra },
    credentials: "include",
  })
  if (!response.ok) throw new Error(await parseError(response))
  return (await response.json()) as T
}

export async function apiSend<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetchApi(path, {
    method,
    headers: { ...scopeHeaders(), "Content-Type": "application/json" },
    credentials: "include",
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await parseError(response))
  return (await response.json()) as T
}

export function listConversations() {
  return apiGet<{ conversations: Conversation[] }>("/api/conversations")
}

export function listMessages(sessionId: string, token: string) {
  return apiGet<{ messages: ChatMessage[] }>(`/api/conversations/${sessionId}/messages`, {
    Authorization: `Bearer ${token}`,
  })
}

export function listDocuments() {
  return apiGet<{ documents: DocumentRow[]; stats: IndexStats }>("/api/documents")
}

export function getDocument(id: string) {
  return apiGet<DocumentRow>(`/api/documents/${id}`)
}

export function deleteDocument(id: string) {
  return apiSend<{ deleted: string }>(`/api/documents/${id}`, "DELETE")
}

export function reindexDocument(id: string) {
  return apiSend<{ id: string; job_id: string; status: string }>(`/api/documents/${id}/reindex`, "POST")
}

export async function uploadDocument(form: FormData) {
  const response = await fetchApi("/api/documents/upload", {
    method: "POST",
    headers: scopeHeaders(),
    credentials: "include",
    body: form,
  })
  if (!response.ok) throw new Error(await parseError(response))
  return (await response.json()) as { id: string; status: string; stage: string }
}

export function listManufacturers() {
  return apiGet<{ manufacturers: Array<Record<string, unknown>>; demo: boolean }>("/api/manufacturers")
}

export function listMcpTools() {
  return apiGet<Record<string, unknown>>("/api/mcp/tools")
}

export function listEvaluations() {
  return apiGet<{ runs: EvalRun[]; dataset_size: number; judge_note: string }>("/api/evaluations")
}

export function getEvaluation(id: string) {
  return apiGet<EvalDetail>(`/api/evaluations/${id}`)
}

export function runEvaluation() {
  return apiSend<EvalDetail>("/api/evaluations/run", "POST", {})
}

export function listTraces() {
  return apiGet<{ traces: TraceSummary[] }>("/api/traces")
}

export function getTrace(messageId: string) {
  return apiGet<TraceDetail>(`/api/chat/${messageId}/trace`)
}

export function sendFeedback(messageId: string, rating: number, comment: string) {
  return apiSend<{ id: string }>("/api/feedback", "POST", { message_id: messageId, rating, comment })
}

export interface SseEvent {
  event: string
  data: Record<string, unknown>
}

export function parseSseBlock(block: string): SseEvent | null {
  const trimmed = block.trim()
  if (!trimmed || trimmed.startsWith(":")) return null
  let event = "message"
  const dataLines: string[] = []
  for (const line of trimmed.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim()
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return { event, data: {} }
  return { event, data: JSON.parse(dataLines.join("\n")) as Record<string, unknown> }
}

export async function streamChat(
  body: {
    message: string
    session_token?: string
    manufacturer?: string
    machine_model?: string
  },
  signal: AbortSignal,
  onEvent: (event: SseEvent) => void,
): Promise<void> {
  const response = await fetchApi("/api/chat/stream", {
    method: "POST",
    headers: {
      ...scopeHeaders(),
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    credentials: "include",
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) throw new Error(await parseError(response))
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let sawDone = false
  while (true) {
    const read = await reader.read()
    if (read.done) break
    buffer += decoder.decode(read.value, { stream: true })
    const blocks = buffer.split("\n\n")
    buffer = blocks.pop() ?? ""
    for (const block of blocks) {
      const parsed = parseSseBlock(block)
      if (!parsed) continue
      onEvent(parsed)
      if (parsed.event === "done") sawDone = true
    }
  }
  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer)
    if (parsed) {
      onEvent(parsed)
      if (parsed.event === "done") sawDone = true
    }
  }
  if (!sawDone) throw new Error("The stream closed before the assistant finished.")
}
