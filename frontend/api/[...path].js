export const config = {
  runtime: "edge",
}

function json(message, status) {
  return Response.json({ message }, { status })
}

/** Same-origin /api on Vercel. The browser never calls 127.0.0.1. */
export default async function handler(request) {
  const upstream = (process.env.API_UPSTREAM || process.env.VITE_API_BASE_URL || "").trim().replace(/\/$/, "")
  if (!upstream || upstream.includes("127.0.0.1") || upstream.includes("localhost")) {
    return json("This published site has no public API host. Set API_UPSTREAM to the FastAPI origin.", 503)
  }
  const incoming = new URL(request.url)
  const headers = new Headers(request.headers)
  headers.delete("host")
  const init = {
    method: request.method,
    headers,
    redirect: "manual",
  }
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body
    init.duplex = "half"
  }
  try {
    const response = await fetch(`${upstream}${incoming.pathname}${incoming.search}`, init)
    const out = new Headers(response.headers)
    out.delete("content-encoding")
    out.delete("content-length")
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers: out })
  } catch {
    return json(`Cannot reach the ManualMind API (${upstream}).`, 502)
  }
}
