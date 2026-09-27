"use client";

import { formatRelative } from "@/lib/format";

/** Pause/resume + manual refresh for a polled view, with a freshness readout. */
export function LiveControls({
  live,
  onToggleLive,
  onRefresh,
  lastUpdated,
  intervalMs,
}: {
  live: boolean;
  onToggleLive: () => void;
  onRefresh: () => void;
  lastUpdated: string | null;
  intervalMs: number;
}) {
  return (
    <div className="flex items-center gap-3 text-xs text-ink-muted">
      <span className="flex items-center gap-1.5">
        <span
          className={`h-2 w-2 rounded-full ${
            live ? "animate-pulse bg-green-500" : "bg-ink-faint"
          }`}
          aria-hidden
        />
        {live ? `Live · every ${Math.round(intervalMs / 1000)}s` : "Paused"}
      </span>
      {lastUpdated ? <span aria-live="polite">Updated {formatRelative(lastUpdated)}</span> : null}
      <button
        type="button"
        onClick={onToggleLive}
        className="rounded-md border border-line-strong px-2 py-1 font-medium transition-colors hover:bg-surface-raised hover:text-ink"
      >
        {live ? "Pause" : "Resume"}
      </button>
      <button
        type="button"
        onClick={onRefresh}
        className="rounded-md border border-line-strong px-2 py-1 font-medium transition-colors hover:bg-surface-raised hover:text-ink"
      >
        Refresh
      </button>
    </div>
  );
}
