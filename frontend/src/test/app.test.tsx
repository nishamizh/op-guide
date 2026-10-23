import { render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"

import App from "../App.tsx"
import { parseSseBlock, resolveApiBase } from "../lib/api.ts"

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      const body = url.includes("/documents")
        ? { documents: [], stats: { documents: 0, chunks: 0, indexed: 0, index_revision: 0, embedding_model: "", demo_documents: 0 } }
        : url.includes("/conversations")
          ? { conversations: [] }
          : url.includes("/manufacturers")
            ? { manufacturers: [], demo: true }
            : url.includes("/mcp/tools")
              ? { tools: [], reachable: false, server_url: "http://example", checked_at: "", demo: true }
              : url.includes("/evaluations")
                ? { runs: [], dataset_size: 24, judge_note: "Deterministic checks." }
                : url.includes("/traces")
                  ? { traces: [] }
                  : {}
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } })
    }),
  )
})

const headings: Record<string, RegExp> = {
  "/chat": /Conversations/i,
  "/documents": /Knowledge base/i,
  "/integrations": /MCP integrations/i,
  "/evaluations": /^Evaluations$/i,
  "/traces": /Architecture and trace/i,
}

describe("routes survive a direct load", () => {
  it.each(Object.keys(headings))("renders %s", async (path) => {
    render(
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>,
    )
    expect(await screen.findByRole("heading", { name: headings[path] })).toBeInTheDocument()
    expect(screen.getByText(/DEMO corpus/i)).toBeInTheDocument()
  })
})

describe("resolveApiBase", () => {
  it("keeps a public API and drops a loopback API the page cannot reach", () => {
    expect(resolveApiBase("https://api.example.com", "https://op-guide.example")).toBe("https://api.example.com")
    expect(resolveApiBase("http://127.0.0.1:8091", "http://127.0.0.1:4178")).toBe("")
    expect(resolveApiBase("http://127.0.0.1:8091/", "https://op-guide-lw4a.vercel.app")).toBe("")
    expect(resolveApiBase("", "http://127.0.0.1:4178")).toBe("")
  })
})

describe("parseSseBlock", () => {
  it("reads named events and ignores comments", () => {
    expect(parseSseBlock(": keepalive")).toBeNull()
    expect(parseSseBlock('event: token\ndata: {"text":"E104"}')).toEqual({
      event: "token",
      data: { text: "E104" },
    })
  })
})
