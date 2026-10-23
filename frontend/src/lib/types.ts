export interface Citation {
  evidence_type?: string
  chunk_id?: string
  document_id?: string
  title?: string
  document_title?: string
  revision?: string
  page_start?: number
  page_end?: number
  section_id?: string
  section_ids?: string[]
  snippet?: string
  score?: number
  mock?: boolean
  manufacturer?: string
  machine_model?: string
  tool_name?: string
  status?: string
  succeeded?: boolean
}

export interface Confidence {
  score?: number
  label?: string
  heuristic?: boolean
  calibrated?: boolean
  explanation?: string
  components?: Record<string, number>
  caps?: string[]
}

export interface WarningItem {
  code: string
  message: string
}

export interface ChatMessage {
  id: string
  session_id: string
  role: string
  content: string
  route?: string | null
  citations?: Citation[]
  confidence?: Confidence
  confidence_label?: string | null
  confidence_score?: number | null
  warnings?: WarningItem[]
  blocked?: boolean
  block_reason?: string | null
  created_at?: string | null
  session_token?: string
  user_message_id?: string
}

export interface Conversation {
  id: string
  title: string
  manufacturer?: string | null
  machine_model?: string | null
  updated_at?: string | null
  session_token: string
}

export interface DocumentRow {
  id: string
  title: string
  manufacturer: string
  machine_model: string
  equipment_type: string
  plant: string
  document_revision: string
  effective_date?: string | null
  filename: string
  status: string
  is_demo: boolean
  chunk_count: number
  job?: { id: string; status: string; stage: string; progress: number; error?: string | null } | null
  chunks?: ChunkPreview[]
}

export interface ChunkPreview {
  id: string
  chunk_index: number
  token_count: number
  page_start: number
  page_end: number
  section_id: string
  section_title: string
  revision: string
  injection_suspected: boolean
  preview: string
}

export interface IndexStats {
  documents: number
  chunks: number
  indexed: number
  index_revision: number
  embedding_model: string
  demo_documents: number
}

export interface TraceSummary {
  message_id: string
  session_id: string
  created_at?: string | null
  route?: string | null
  confidence_label?: string | null
  confidence_score?: number | null
  blocked?: boolean
  preview: string
}

export interface TraceDetail {
  message: ChatMessage
  run: {
    id: string
    query: string
    rewritten_query?: string | null
    route?: string | null
    fusion?: Record<string, unknown>
    latency_ms?: number | null
    vector_space?: string | null
    embedding_model?: string | null
    index_revision?: number | null
    attempt?: number | null
    trace?: TraceNode[]
    guardrail?: Record<string, unknown>
  } | null
  evidence: Array<Record<string, unknown>>
  mcp_calls: Array<Record<string, unknown>>
}

export interface TraceNode {
  node?: string
  status?: string
  duration_ms?: number
  output_summary?: Record<string, unknown>
}

export interface EvalRun {
  id: string
  status: string
  metrics: Record<string, number | string | boolean | null>
  experiment: Record<string, unknown>
  started_at?: string | null
  finished_at?: string | null
}

export interface EvalDetail extends EvalRun {
  results: Array<{
    case_id: string
    category: string
    question: string
    scores: Record<string, number | null>
    latency_ms: number
    actual: Record<string, unknown>
  }>
}
