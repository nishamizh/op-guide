import { Send, Square } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"
import { Link } from "react-router-dom"

import { Badge, Button } from "../components/ui.tsx"
import { listConversations, listMessages, sendFeedback, setOperator, streamChat } from "../lib/api.ts"
import type { ChatMessage, Citation, Conversation } from "../lib/types.ts"

const EXAMPLES = [
  "What does Rainer R200 E104 mean?",
  "Why is the coolant pressure low and what approved checks can a technician perform?",
  "Check Rainer R200 current status and compare with the manual.",
  "Which manual revision supports your response?",
  "What if no document or manufacturer tool supports my question?",
]

const MODELS = ["", "R200", "R500", "P300"]

export function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [active, setActive] = useState<Conversation | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState("")
  const [manufacturer, setManufacturer] = useState("")
  const [model, setModel] = useState("")
  const [streaming, setStreaming] = useState("")
  const [status, setStatus] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const abortRef = useRef<AbortController | null>(null)
  const scroller = useRef<HTMLDivElement | null>(null)
  const pending = useRef<{ message: string; token?: string } | null>(null)

  async function refreshConversations() {
    const payload = await listConversations()
    setConversations(payload.conversations)
    return payload.conversations
  }

  useEffect(() => {
    refreshConversations().catch((err: Error) => setError(err.message))
  }, [])

  useEffect(() => {
    scroller.current?.scrollTo?.({ top: scroller.current.scrollHeight })
  }, [messages, streaming])

  async function openConversation(conversation: Conversation) {
    setActive(conversation)
    setError("")
    setManufacturer(conversation.manufacturer || "")
    setModel(conversation.machine_model || "")
    try {
      const payload = await listMessages(conversation.id, conversation.session_token)
      setMessages(payload.messages)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this conversation.")
    }
  }

  function stop() {
    abortRef.current?.abort()
    setBusy(false)
    setStatus("Stopped")
  }

  async function recover(token: string | undefined, sessionId: string | undefined) {
    if (!token || !sessionId) return false
    try {
      const payload = await listMessages(sessionId, token)
      if (payload.messages.some((item) => item.role === "assistant")) {
        setMessages(payload.messages)
        setStreaming("")
        setNotice("Reconnected to the saved conversation.")
        return true
      }
    } catch {
      return false
    }
    return false
  }

  async function ask(text: string) {
    const message = text.trim()
    if (!message || busy) return
    setError("")
    setNotice("")
    setDraft("")
    setBusy(true)
    setStreaming("")
    setStatus("Connecting")
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      session_id: active?.id || "",
      role: "user",
      content: message,
    }
    setMessages((current) => [...current, optimistic])
    const controller = new AbortController()
    abortRef.current = controller
    let sessionId = active?.id
    let token = active?.session_token
    pending.current = { message, token }
    try {
      await streamChat(
        {
          message,
          session_token: token,
          manufacturer: manufacturer || undefined,
          machine_model: model || undefined,
        },
        controller.signal,
        (event) => {
          if (event.event === "status") {
            const node = String(event.data.node || "working")
            setStatus(node.replaceAll("_", " "))
          }
          if (event.event === "token") {
            setStreaming((current) => current + String(event.data.text || ""))
          }
          if (event.event === "session") {
            sessionId = String(event.data.session_id || sessionId || "")
            token = String(event.data.session_token || token || "")
            pending.current = { message, token }
          }
          if (event.event === "error") {
            throw new Error(String(event.data.message || "The assistant failed."))
          }
          if (event.event === "result") {
            const result = event.data as unknown as ChatMessage
            setStreaming("")
            setMessages((current) => [...current.filter((item) => item.id !== optimistic.id), optimistic, result])
            if (result.session_id && result.session_token) {
              const conversation: Conversation = {
                id: result.session_id,
                title: message.slice(0, 80),
                manufacturer: manufacturer || null,
                machine_model: model || null,
                session_token: result.session_token,
              }
              setActive(conversation)
              sessionId = conversation.id
              token = conversation.session_token
            }
          }
        },
      )
      await refreshConversations()
    } catch (err) {
      if (controller.signal.aborted) return
      const recovered = await recover(token, sessionId)
      if (!recovered) {
        setError(err instanceof Error ? err.message : "The stream failed.")
        setNotice("The reply was not saved. Retry sends the same question again.")
      }
    } finally {
      setBusy(false)
      setStatus("")
      abortRef.current = null
    }
  }

  const placeholder = useMemo(
    () => (manufacturer || model ? `Ask about ${manufacturer || "any manufacturer"} ${model}`.trim() : "Ask about a demo alarm, limit, or status"),
    [manufacturer, model],
  )

  return (
    <div className="grid gap-4 lg:grid-cols-[240px_1fr]">
      <aside className="rounded-xl border border-stone-200 bg-white">
        <div className="flex items-center justify-between border-b border-stone-100 px-3 py-3">
          <h1 className="text-sm font-semibold">Conversations</h1>
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setActive(null)
              setMessages([])
              setStreaming("")
              setError("")
            }}
          >
            New
          </Button>
        </div>
        <div className="max-h-[70vh] overflow-auto p-2">
          {conversations.length === 0 && <p className="px-2 py-4 text-sm text-stone-500">No saved chats for this operator yet.</p>}
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              type="button"
              onClick={() => void openConversation(conversation)}
              className={`mb-1 w-full rounded-md px-2 py-2 text-left text-sm ${active?.id === conversation.id ? "bg-stone-200" : "hover:bg-stone-50"}`}
            >
              <span className="line-clamp-2 font-medium">{conversation.title}</span>
              <span className="mt-1 block text-xs text-stone-500">
                {[conversation.manufacturer, conversation.machine_model].filter(Boolean).join(" ") || "No equipment filter"}
              </span>
            </button>
          ))}
        </div>
      </aside>
      <section className="flex min-h-[70vh] flex-col rounded-xl border border-stone-200 bg-white">
        <div className="flex flex-wrap items-end gap-3 border-b border-stone-100 px-4 py-3">
          <label className="text-xs font-semibold uppercase tracking-wide text-stone-500">
            Manufacturer
            <input
              className="mt-1 block h-9 rounded-md border border-stone-300 px-2 text-sm font-normal normal-case"
              value={manufacturer}
              placeholder="Rainer"
              onChange={(event) => {
                setManufacturer(event.target.value)
                setOperator("demo", "operator")
              }}
            />
          </label>
          <label className="text-xs font-semibold uppercase tracking-wide text-stone-500">
            Model
            <select className="mt-1 block h-9 rounded-md border border-stone-300 px-2 text-sm font-normal" value={model} onChange={(event) => setModel(event.target.value)}>
              {MODELS.map((item) => (
                <option key={item || "any"} value={item}>
                  {item || "Any"}
                </option>
              ))}
            </select>
          </label>
          <p className="pb-2 text-xs text-stone-500">Filters are optional. Mock tools run only for Rainer and Acme Industrial.</p>
        </div>
        <div ref={scroller} className="flex-1 space-y-4 overflow-auto px-4 py-4">
          {messages.length === 0 && !streaming && (
            <div>
              <h2 className="text-lg font-semibold">Ask the demo floor manual</h2>
              <p className="mt-1 max-w-2xl text-sm text-stone-600">
                Answers cite stored page and section ids from the fictional Rainer and Acme manuals, or a clearly labeled mock tool fixture.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                {EXAMPLES.map((example) => (
                  <button key={example} type="button" className="rounded-full border border-stone-300 px-3 py-1 text-left text-sm hover:bg-stone-50" onClick={() => void ask(example)}>
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {streaming && (
            <article className="rounded-lg bg-stone-50 px-3 py-3 text-sm whitespace-pre-wrap">
              {streaming}
              <span className="ml-1 inline-block h-3 w-2 animate-pulse bg-signal" />
            </article>
          )}
          {busy && status && <p className="font-mono text-xs text-stone-500">Agent: {status}</p>}
          {error && <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>}
          {notice && <p className="text-sm text-stone-600">{notice}</p>}
        </div>
        <form
          className="flex items-end gap-2 border-t border-stone-100 p-3"
          onSubmit={(event) => {
            event.preventDefault()
            void ask(draft)
          }}
        >
          <textarea
            className="min-h-12 flex-1 resize-none rounded-md border border-stone-300 px-3 py-2 text-sm"
            rows={2}
            value={draft}
            placeholder={placeholder}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault()
                void ask(draft)
              }
            }}
          />
          {busy ? (
            <Button type="button" variant="outline" onClick={stop} aria-label="Stop generating">
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button type="submit" variant="signal" aria-label="Send question">
              <Send className="h-4 w-4" />
            </Button>
          )}
          {notice.includes("Retry") && pending.current && (
            <Button type="button" variant="outline" onClick={() => void ask(pending.current?.message || "")}>
              Retry
            </Button>
          )}
        </form>
      </section>
    </div>
  )
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const [comment, setComment] = useState("")
  const [saved, setSaved] = useState("")
  if (message.role === "user") {
    return <article className="ml-8 rounded-lg bg-ink px-3 py-2 text-sm text-paper">{message.content}</article>
  }
  const confidence = message.confidence
  return (
    <article className="rounded-lg border border-stone-200 px-3 py-3 text-sm">
      <div className="mb-2 flex flex-wrap gap-2">
        {message.route && <Badge tone="stone">{message.route}</Badge>}
        {message.confidence_label && <Badge tone={message.confidence_label === "low" ? "red" : "amber"}>{`${message.confidence_label} heuristic`}</Badge>}
        {message.blocked && <Badge tone="red">blocked</Badge>}
      </div>
      <div className="whitespace-pre-wrap leading-6">{message.content}</div>
      {confidence?.explanation && <p className="mt-3 text-xs text-stone-600">{confidence.explanation}</p>}
      {!!message.warnings?.length && (
        <ul className="mt-3 space-y-1">
          {message.warnings.map((warning) => (
            <li key={warning.code + warning.message} className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-950">
              {warning.code}: {warning.message}
            </li>
          ))}
        </ul>
      )}
      {!!message.citations?.length && (
        <div className="mt-3 grid gap-2">
          {message.citations.map((citation, index) => (
            <CitationCard key={`${citation.chunk_id || citation.tool_name}-${index}`} citation={citation} />
          ))}
        </div>
      )}
      <form
        className="mt-3 flex flex-wrap items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault()
        }}
      >
        <span className="text-xs text-stone-500">Was this usable?</span>
        {[1, -1].map((rating) => (
          <Button
            key={rating}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              void sendFeedback(message.id, rating, comment)
                .then(() => setSaved(rating > 0 ? "Marked helpful" : "Marked unhelpful"))
                .catch((err: Error) => setSaved(err.message))
            }}
          >
            {rating > 0 ? "Helpful" : "Not helpful"}
          </Button>
        ))}
        <input className="h-8 flex-1 rounded-md border border-stone-300 px-2 text-xs" placeholder="Optional note" value={comment} onChange={(event) => setComment(event.target.value)} />
        {saved && <span className="text-xs text-stone-500">{saved}</span>}
      </form>
    </article>
  )
}

function CitationCard({ citation }: { citation: Citation }) {
  const [open, setOpen] = useState(false)
  const mock = citation.evidence_type === "mcp" || citation.mock
  return (
    <div className="rounded-md border border-stone-200 bg-stone-50 px-3 py-2">
      <button type="button" className="flex w-full items-start justify-between gap-3 text-left" onClick={() => setOpen((value) => !value)}>
        <span>
          <span className="font-semibold">{citation.title || citation.tool_name}</span>
          <span className="mt-1 block text-xs text-stone-500">
            {mock ? "MCP mock fixture" : "Manual"} · rev {citation.revision || "n/a"}
            {citation.page_start ? ` · page ${citation.page_start}` : ""}
            {citation.section_id ? ` · ${citation.section_id}` : ""}
            {citation.status ? ` · ${citation.status}` : ""}
          </span>
        </span>
        <Badge tone={mock ? "amber" : "green"}>{mock ? "mock tool" : "manual"}</Badge>
      </button>
      {open && (
        <div className="mt-2 text-xs text-stone-700">
          <p>{citation.snippet || "No snippet stored."}</p>
          {citation.document_id && (
            <Link className="mt-2 inline-block font-semibold text-signal" to={`/documents/${citation.document_id}`}>
              Open source document
            </Link>
          )}
          {citation.chunk_id && <p className="mt-1 font-mono">chunk:{citation.chunk_id}</p>}
        </div>
      )}
    </div>
  )
}
