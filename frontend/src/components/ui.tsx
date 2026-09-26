import type { ReactNode } from "react";

type Tone = "green" | "red" | "orange" | "blue" | "zinc";

const TONE_CLASSES: Record<Tone, string> = {
  green:
    "bg-green-50 text-green-700 ring-green-600/20 dark:bg-green-500/10 dark:text-green-300 dark:ring-green-400/20",
  red: "bg-red-50 text-red-700 ring-red-600/20 dark:bg-red-500/10 dark:text-red-300 dark:ring-red-400/20",
  orange:
    "bg-orange-50 text-orange-800 ring-orange-600/20 dark:bg-orange-500/10 dark:text-orange-300 dark:ring-orange-400/20",
  blue: "bg-blue-50 text-blue-700 ring-blue-600/20 dark:bg-blue-500/10 dark:text-blue-300 dark:ring-blue-400/20",
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
    <div
      className={`rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950 ${className}`}
    >
      {children}
    </div>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-[0.85em] break-all text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
      {children}
    </code>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-500">
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
      <p className="font-medium text-zinc-900 dark:text-zinc-100">{title}</p>
      {children ? <div className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">{children}</div> : null}
    </Card>
  );
}

/** Long strings (logs, findings, JSON) in a scroll-capped preformatted block. */
export function CodeBlock({ children }: { children: string }) {
  return (
    <pre className="max-h-80 overflow-auto rounded-lg bg-zinc-50 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap text-zinc-700 ring-1 ring-zinc-200 ring-inset dark:bg-zinc-900 dark:text-zinc-300 dark:ring-zinc-800">
      {children}
    </pre>
  );
}
