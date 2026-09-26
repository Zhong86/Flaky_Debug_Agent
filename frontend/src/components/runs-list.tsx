"use client";

import Link from "next/link";
import { useState } from "react";

import { listRuns } from "@/lib/api";
import { formatRelative, formatTimestamp, repoName } from "@/lib/format";
import type { RunSummary } from "@/lib/types";
import { usePoll } from "@/lib/use-poll";
import { LiveControls } from "./live-controls";
import { Card, EmptyState, ErrorBanner, Pill, SectionLabel, Verdict } from "./ui";

const POLL_MS = 5000;

/** documenter_agent stores an "[… error] …" message instead of a path when Bob fails. */
function hasReport(run: RunSummary): boolean {
  return Boolean(run.document) && !run.document?.startsWith("[");
}

/** One-line outcome for a run: the flaky verdict, and whether its report is written. */
function outcome(run: RunSummary) {
  if (run.is_flaky === false) return { tone: "red" as const, label: "Real failure" };
  if (run.is_flaky === true && hasReport(run)) return { tone: "orange" as const, label: "Flaky · reported" };
  if (run.is_flaky === true) return { tone: "orange" as const, label: "Flaky · investigating" };
  return { tone: "zinc" as const, label: "Running" };
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <Card className="px-4 py-3">
      <SectionLabel>{label}</SectionLabel>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-900 dark:text-zinc-50">{value}</p>
    </Card>
  );
}

export function RunsList() {
  const [live, setLive] = useState(true);
  const { data, error, loading, lastUpdated, refresh } = usePoll(
    (signal) => listRuns(50, { signal }),
    live ? POLL_MS : null,
  );

  if (loading) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading runs…</p>;
  }

  if (error && !data) {
    return (
      <ErrorBanner
        error={error}
        hint="Is the backend running? Start Postgres with `docker compose up -d` and the API with `uv run uvicorn main:app --app-dir src --port 8000` from backend/."
      />
    );
  }

  const runs = data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SectionLabel>Overview</SectionLabel>
        <LiveControls
          live={live}
          onToggleLive={() => setLive((v) => !v)}
          onRefresh={refresh}
          lastUpdated={lastUpdated}
          intervalMs={POLL_MS}
        />
      </div>

      {/* A refresh may fail while stale data is still on screen — say so without wiping it. */}
      {error ? (
        <p className="text-xs text-red-600 dark:text-red-400">
          Last refresh failed ({error.message}). Showing the most recent successful fetch.
        </p>
      ) : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Runs" value={runs.length} />
        <Stat label="Flaky" value={runs.filter((r) => r.is_flaky === true).length} />
        <Stat label="Real failures" value={runs.filter((r) => r.is_flaky === false).length} />
        <Stat label="Reports" value={runs.filter(hasReport).length} />
      </div>

      {runs.length === 0 ? (
        <EmptyState title="No runs recorded yet">
          Runs appear here once the GitHub webhook invokes the graph. Every checkpointed{" "}
          <code className="font-mono">thread_id</code> becomes a row.
        </EmptyState>
      ) : (
        <ul className="space-y-3">
          {runs.map((run) => {
            const { tone, label } = outcome(run);
            const repo = repoName(run.repository);
            return (
              <li key={run.thread_id}>
                <Link
                  href={`/runs/${encodeURIComponent(run.thread_id)}`}
                  className="block rounded-xl border border-zinc-200 bg-white p-4 transition-colors hover:border-zinc-300 hover:bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950 dark:hover:border-zinc-700 dark:hover:bg-zinc-900"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-sm font-medium text-zinc-900 dark:text-zinc-100">
                          {run.thread_id}
                        </span>
                        <Pill tone={tone}>{label}</Pill>
                      </div>
                      <p className="mt-1 truncate text-sm text-zinc-500 dark:text-zinc-400">
                        {repo ?? "Unknown repository"}
                      </p>
                    </div>
                    <div className="text-right text-xs text-zinc-500 dark:text-zinc-400">
                      <p>{formatTimestamp(run.updated_at)}</p>
                      <p>{formatRelative(run.updated_at)}</p>
                    </div>
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <Verdict
                      value={run.is_flaky}
                      trueLabel="Flaky"
                      falseLabel="Real failure"
                      trueTone="orange"
                      pendingLabel="Not classified"
                    />
                    {hasReport(run) ? <Pill tone="green">Report written</Pill> : null}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
