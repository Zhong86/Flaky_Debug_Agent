import type { ReactNode } from "react";

/** Green = good, orange = needs attention, red = outright failure, zinc = not yet known. */
type Tone = "green" | "red" | "orange" | "zinc";

const TONE_CLASSES: Record<Tone, string> = {
  green:
    "bg-green-50 text-green-700 ring-green-600/20 dark:bg-green-500/10 dark:text-green-300 dark:ring-green-400/20",
  red: "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-400/20",
  orange:
    "bg-orange-50 text-orange-800 ring-orange-600/20 dark:bg-orange-500/10 dark:text-orange-300 dark:ring-orange-400/20",
  zinc: "bg-zinc-100 text-zinc-600 ring-zinc-500/20 dark:bg-zinc-500/10 dark:text-zinc-400 dark:ring-zinc-400/20",
};

export function Pill({ tone = "zinc", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}

/**
 * Renders one of the graph's tri-state booleans. `undefined`/`null` means the
 * node that writes it hasn't run yet — which is information, not an error.
 */
export function Verdict({
  value,
  trueLabel,
  falseLabel,
  pendingLabel = "Pending",
  trueTone = "green",
  falseTone = "red",
}: {
  value: boolean | null | undefined;
  trueLabel: string;
  falseLabel: string;
  pendingLabel?: string;
  trueTone?: Tone;
  falseTone?: Tone;
}) {
  if (value === null || value === undefined) return <Pill tone="zinc">{pendingLabel}</Pill>;
  return value ? <Pill tone={trueTone}>{trueLabel}</Pill> : <Pill tone={falseTone}>{falseLabel}</Pill>;
}

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-xl border border-line bg-surface ${className}`}>
      {children}
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-surface-raised px-1.5 py-0.5 font-mono text-[0.85em] break-all text-ink-soft">
      {children}
    </code>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-xs font-semibold tracking-wide text-ink-faint uppercase">
      {children}
    </h3>
  );
}

export function ErrorBanner({ error, hint }: { error: Error; hint?: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm dark:border-red-500/30 dark:bg-red-500/10">
      <p className="font-medium text-red-800 dark:text-red-300">{error.message}</p>
      {hint ? <p className="mt-1 text-red-700/80 dark:text-red-300/70">{hint}</p> : null}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <Card className="p-10 text-center">
      <p className="font-medium text-ink">{title}</p>
      {children ? <div className="mt-2 text-sm text-ink-muted">{children}</div> : null}
    </Card>
  );
}

/** Long strings (logs, findings, JSON) in a scroll-capped preformatted block. */
export function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-lg bg-surface-sunken p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-ink-soft ring-1 ring-line ring-inset">
      {children}
    </pre>
  );
}
