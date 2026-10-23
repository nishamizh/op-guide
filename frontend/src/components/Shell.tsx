import { BookOpen, ClipboardList, Menu, MessageSquare, Unplug, Waypoints } from "lucide-react"
import { useState } from "react"
import { NavLink, Outlet } from "react-router-dom"

import { cn } from "../lib/utils.ts"

const links = [
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/documents", label: "Knowledge base", icon: BookOpen },
  { to: "/integrations", label: "MCP integrations", icon: Unplug },
  { to: "/evaluations", label: "Evaluations", icon: ClipboardList },
  { to: "/traces", label: "Architecture", icon: Waypoints },
]

export function Shell() {
  const [open, setOpen] = useState(false)
  return (
    <div className="min-h-screen md:grid md:grid-cols-[240px_1fr]">
      <aside className={cn("border-b border-stone-800 bg-ink text-paper md:min-h-screen md:border-b-0 md:border-r", open ? "block" : "hidden md:block")}>
        <div className="px-4 py-5">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-200">ManualMind</p>
          <p className="mt-1 text-sm text-stone-300">Factory manual assistant</p>
        </div>
        <nav className="flex flex-col gap-1 px-2 pb-6">
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm",
                  isActive ? "bg-white/10 text-white" : "text-stone-300 hover:bg-white/5 hover:text-white",
                )
              }
            >
              <link.icon className="h-4 w-4" aria-hidden />
              {link.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="flex items-center justify-between gap-3 border-b border-stone-200 bg-paper px-4 py-3 md:hidden">
          <button type="button" className="rounded-md border border-stone-300 p-2" onClick={() => setOpen((value) => !value)} aria-label="Open navigation">
            <Menu className="h-4 w-4" />
          </button>
          <p className="font-mono text-xs uppercase tracking-[0.18em]">ManualMind</p>
        </header>
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-950">
          DEMO corpus and mock manufacturer tools. Readings are fixtures, not live telemetry, and must not be used on real equipment.
        </div>
        <main className="px-4 py-5 md:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
