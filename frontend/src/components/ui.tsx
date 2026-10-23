import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import type { ButtonHTMLAttributes, ReactNode } from "react"

import { cn } from "../lib/utils.ts"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-semibold transition disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-ink text-paper hover:bg-stone-800",
        signal: "bg-signal text-white hover:bg-orange-800",
        ghost: "hover:bg-stone-200/80",
        outline: "border border-stone-300 bg-white hover:bg-stone-50",
      },
      size: {
        default: "h-10 px-4",
        sm: "h-8 px-3 text-xs",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button"
  return <Comp className={cn(buttonVariants({ variant, size }), className)} {...props} />
}

export function Badge({ children, tone = "stone" }: { children: string; tone?: "stone" | "amber" | "green" | "red" }) {
  const tones = {
    stone: "bg-stone-200 text-stone-800",
    amber: "bg-amber-100 text-amber-950",
    green: "bg-lime-100 text-lime-950",
    red: "bg-red-100 text-red-900",
  }
  return (
    <span className={cn("inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold uppercase tracking-wide", tones[tone])}>
      {children}
    </span>
  )
}

export function Panel({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="rounded-xl border border-stone-200 bg-white shadow-sm">
      <header className="flex items-center justify-between gap-3 border-b border-stone-100 px-4 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-stone-500">{title}</h2>
        {action}
      </header>
      <div className="p-4">{children}</div>
    </section>
  )
}
