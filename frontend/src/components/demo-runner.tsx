"use client";

import { useState } from "react";

import { dispatchDemoRun, getBackendLogs, getDemoConfig, getDemoJobLogs, getDemoRun } from "@/lib/api";
import { formatBackendLogs, runStatusTone } from "@/lib/format";
import type { DemoJob, DemoRun } from "@/lib/types";
import { usePoll } from "@/lib/use-poll";
import { LiveControls } from "./live-controls";
import { Card, CodeBlock, ErrorBanner, Pill, SectionLabel } from "./ui";

const RUN_POLL_MS = 3000;
const LOG_POLL_MS = 4000;
const BACKEND_LOG_POLL_MS = 2000;

function StatusPill({ status, conclusion }: { status: string; conclusion: string | null }) {
  return <Pill tone={runStatusTone(status, conclusion)}>{status === "completed" ? (conclusion ?? status) : status}</Pill>;
}

/** The job worth showing logs for: whichever is running, else the last one. */
function activeJobId(jobs: DemoJob[]): number | null {
  return (jobs.find((job) => job.status === "in_progress") ?? jobs.at(-1))?.id ?? null;
}

function JobList({
  jobs,
  selectedJobId,
  onSelect,
}: {
  jobs: DemoJob[];
  selectedJobId: number | null;
  onSelect: (jobId: number) => void;
}) {
  if (jobs.length === 0) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">Waiting for jobs to appear…</p>;
  }
  return (
    <ul className="space-y-2">
      {jobs.map((job) => (
        <li key={job.id}>
          <button
            type="button"
            onClick={() => onSelect(job.id)}
            className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
              selectedJobId === job.id
                ? "border-zinc-400 bg-zinc-50 dark:border-zinc-600 dark:bg-zinc-900"
                : "border-zinc-200 hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900"
            }`}
          >
            <span className="font-medium text-zinc-900 dark:text-zinc-100">{job.name}</span>
            <StatusPill status={job.status} conclusion={job.conclusion} />
          </button>
          {job.steps.length > 0 ? (
            <ul className="mt-1 ml-3 space-y-1 border-l border-zinc-200 pl-3 dark:border-zinc-800">
              {job.steps.map((step) => (
                <li
                  key={step.number}
                  className="flex items-center justify-between gap-3 text-xs text-zinc-500 dark:text-zinc-400"
                >
                  <span>{step.name}</span>
                  <StatusPill status={step.status} conclusion={step.conclusion} />
                </li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Dispatch deploy.yml on DEMO_REPO and watch it run — `gh run watch`, in the browser. */
export function DemoRunner() {
  const [live, setLive] = useState(true);
  const [runId, setRunId] = useState<number | null>(null);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchError, setDispatchError] = useState<Error | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);

  // DEMO_REPO can't change under a running backend, so this rides usePoll's
  // fire-once-immediately behaviour with no interval rather than polling.
  const { data: demoConfig } = usePoll((signal) => getDemoConfig({ signal }), null);

  // usePoll always fires its fetcher once immediately regardless of intervalMs, so
  // each fetcher below must no-op (resolve null) until it has something to fetch.
  const {
    data: run,
    error: runError,
    lastUpdated,
    refresh,
  } = usePoll<DemoRun | null>(
    (signal) => (runId ? getDemoRun(runId, { signal }) : Promise.resolve(null)),
    runId && live ? RUN_POLL_MS : null,
  );

  const jobs = run?.jobs ?? [];
  const currentJobId = selectedJobId ?? activeJobId(jobs);

  const { data: jobLogs } = usePoll(
    (signal) => (currentJobId ? getDemoJobLogs(currentJobId, { signal }) : Promise.resolve(null)),
    currentJobId && live ? LOG_POLL_MS : null,
  );

  const { data: backendLogs } = usePoll(
    (signal) => getBackendLogs(200, { signal }),
    live ? BACKEND_LOG_POLL_MS : null,
  );

  async function onDispatch() {
    setDispatching(true);
    setDispatchError(null);
    try {
      const result = await dispatchDemoRun();
      setSelectedJobId(null);
      setRunId(result.run_id);
    } catch (err) {
      setDispatchError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setDispatching(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {/* border-transparent carries no colour; it matches the bordered "Demo repo" link's height. */}
          <button
            type="button"
            onClick={onDispatch}
            disabled={dispatching}
            className="rounded-md border border-transparent bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {dispatching ? "Dispatching…" : runId ? "Run again" : "Run Deploy"}
          </button>
          {demoConfig?.actions_url ? (
            <a
              href={demoConfig.actions_url}
              target="_blank"
              rel="noreferrer"
              title={`${demoConfig.repo} — ${demoConfig.workflow_file} on ${demoConfig.ref}`}
              className="rounded-md border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-900"
            >
              Demo repo ↗
            </a>
          ) : null}
          {run ? (
            <a
              href={run.html_url}
              target="_blank"
              rel="noreferrer"
              className="text-xs font-medium text-zinc-500 underline hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
            >
              View on GitHub ↗
            </a>
          ) : null}
        </div>
        <LiveControls
          live={live}
          onToggleLive={() => setLive((v) => !v)}
          onRefresh={refresh}
          lastUpdated={lastUpdated}
          intervalMs={RUN_POLL_MS}
        />
      </div>

      {dispatchError ? (
        <ErrorBanner error={dispatchError} hint="Is DEMO_REPO configured and reachable with GITHUB_TOKEN?" />
      ) : null}
      {runError && !run ? <ErrorBanner error={runError} /> : null}

      {run ? (
        <Card className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <SectionLabel>Run #{run.run_id}</SectionLabel>
            <StatusPill status={run.status} conclusion={run.conclusion} />
          </div>
          <div className="mt-3">
            <JobList jobs={jobs} selectedJobId={currentJobId} onSelect={setSelectedJobId} />
          </div>
        </Card>
      ) : (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          Nothing dispatched yet. Click &ldquo;Run Deploy&rdquo; to trigger deploy.yml and watch it here.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <SectionLabel>GitHub Actions logs</SectionLabel>
          <div className="mt-2">
            <CodeBlock>{jobLogs?.available ? jobLogs.logs : "Waiting for logs…"}</CodeBlock>
          </div>
        </div>
        <div>
          <SectionLabel>Agent backend logs</SectionLabel>
          <div className="mt-2">
            <CodeBlock>{formatBackendLogs(backendLogs?.entries ?? [])}</CodeBlock>
          </div>
        </div>
      </div>
    </div>
  );
}
