"use client";

import Link from "next/link";
import { useState } from "react";

import { ApiError, getRunTimeline } from "@/lib/api";
import {
  NODE_META,
  formatTimestamp,
  nodeLabel,
  repoName,
  stateKeyLabel,
  stepDuration,
  visibleDiffEntries,
} from "@/lib/format";
import type { GraphValues, RunStep } from "@/lib/types";
import { usePoll } from "@/lib/use-poll";
import { LiveControls } from "./live-controls";
import { RerunResultsTable, StateValue } from "./state-value";
import { Card, CodeBlock, EmptyState, ErrorBanner, Mono, Pill, SectionLabel, Verdict } from "./ui";

const POLL_MS = 4000;

/** The six things the graph concludes, pulled from the final state. */
function RunSummaryPanel({ values, pending }: { values: GraphValues; pending: string[] }) {
  const reruns = values.rerun_results ?? [];

  return (
    <div className="space-y-4">
      {/* clone_repo writes "" when the checkout fails, which makes every downstream
          agent conclusion suspect — call that out rather than burying it. */}
      {values.repo_path === "" ? (
        <div className="rounded-xl border border-orange-300 bg-orange-50 p-3 text-sm text-orange-900 dark:border-orange-500/30 dark:bg-orange-500/10 dark:text-orange-200">
          <span className="font-medium">Repository clone failed.</span> The debug agent ran without a checkout, so
          findings below may be unreliable.
        </div>
      ) : null}

      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SectionLabel>Failing tests</SectionLabel>
          {pending.length ? <Pill tone="blue">Waiting on {pending.join(", ")}</Pill> : null}
        </div>
        <div className="mt-3">
          {reruns.length ? (
            <RerunResultsTable results={reruns} />
          ) : (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">No rerun results in state yet.</p>
          )}
        </div>
      </Card>

      <div className="grid gap-3 sm:grid-cols-3">
        <Card className="p-4">
          <SectionLabel>Classification</SectionLabel>
          <div className="mt-2">
            <Verdict
              value={values.is_flaky}
              trueLabel="Flaky"
              falseLabel="Real failure"
              trueTone="orange"
              pendingLabel="Not classified"
            />
          </div>
        </Card>
        <Card className="p-4">
          <SectionLabel>Code fix</SectionLabel>
          <div className="mt-2">
            <Verdict
              value={values.fix_applied}
              trueLabel="Applied"
              falseLabel="Not applied"
              pendingLabel="Not attempted"
            />
          </div>
        </Card>
        <Card className="p-4">
          <SectionLabel>Retest</SectionLabel>
          <div className="mt-2">
            <Verdict value={values.retest_passed} trueLabel="Passed" falseLabel="Failed" pendingLabel="Not run" />
          </div>
        </Card>
      </div>

      {values.debug_findings ? (
        <Card className="p-4">
          <SectionLabel>Debug agent findings</SectionLabel>
          <p className="mt-2 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{values.debug_findings}</p>
        </Card>
      ) : null}

      {values.document ? (
        <Card className="p-4">
          <SectionLabel>Report</SectionLabel>
          <p className="mt-2">
            <Mono>{values.document}</Mono>
          </p>
        </Card>
      ) : null}
    </div>
  );
}

function TimelineEntry({ step, previous }: { step: RunStep; previous: RunStep | undefined }) {
  const entries = visibleDiffEntries(step.changed);
  const duration = stepDuration(step, previous);
  const meta = step.node ? NODE_META[step.node] : undefined;
  // step -1 is the empty checkpoint LangGraph writes before any node runs.
  const isBookkeeping = step.node === null;

  return (
    <li className="relative pl-8">
      {/* Timeline rail + dot */}
      <span
        className="absolute top-3 left-[9px] h-full w-px bg-zinc-200 last:hidden dark:bg-zinc-800"
        aria-hidden
      />
      <span
        className={`absolute top-2.5 left-1.5 h-2.5 w-2.5 rounded-full ring-4 ring-white dark:ring-zinc-950 ${
          isBookkeeping ? "bg-zinc-300 dark:bg-zinc-700" : "bg-blue-500"
        }`}
        aria-hidden
      />

      <Card className="p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <h3 className="font-medium text-zinc-900 dark:text-zinc-100">
              {isBookkeeping && step.step < 0 ? "Run created" : nodeLabel(step.node)}
            </h3>
            {step.node && step.node !== "__start__" ? (
              <span className="font-mono text-xs text-zinc-400 dark:text-zinc-500">{step.node}</span>
            ) : null}
          </div>
          <div className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
            <span>step {step.step}</span>
            {duration ? <span className="tabular-nums">· {duration}</span> : null}
            <span>· {formatTimestamp(step.created_at)}</span>
          </div>
        </div>

        {meta?.blurb ? <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{meta.blurb}</p> : null}

        {entries.length > 0 ? (
          <dl className="mt-3 space-y-3">
            {entries.map(([key, value]) => (
              <div key={key}>
                <dt className="text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-500">
                  {stateKeyLabel(key)}
                </dt>
                <dd className="mt-1">
                  <StateValue name={key} value={value} />
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
            {isBookkeeping ? "Checkpoint written before the first node ran." : "Wrote no new state."}
          </p>
        )}

        <details className="group mt-3">
          <summary className="cursor-pointer text-xs font-medium text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200">
            Full state at this step
          </summary>
          <div className="mt-2">
            <CodeBlock>{JSON.stringify(step.values, null, 2)}</CodeBlock>
          </div>
        </details>
      </Card>
    </li>
  );
}

export function RunDetail({ threadId }: { threadId: string }) {
  const [live, setLive] = useState(true);
  const { data, error, loading, lastUpdated, refresh } = usePoll(
    (signal) => getRunTimeline(threadId, { signal }),
    live ? POLL_MS : null,
  );

  if (loading) {
    return <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading run…</p>;
  }

  if (error && !data) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <EmptyState title={`No run found for ${threadId}`}>
          Either the thread_id is wrong or the graph never checkpointed under it.{" "}
          <Link href="/" className="underline">
            Back to all runs
          </Link>
        </EmptyState>
      );
    }
    return <ErrorBanner error={error} hint="The backend API is unreachable or returned an error." />;
  }

  const steps = data?.steps ?? [];
  const last = steps.at(-1);
  const finalValues = last?.values ?? {};
  // A non-empty `next` on the final snapshot means the graph hasn't finished.
  const pending = last?.next ?? [];
  const repo = repoName(finalValues.github_payload?.repository as never);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            href="/"
            className="text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100"
          >
            ← All runs
          </Link>
          <h1 className="mt-1 font-mono text-xl font-semibold text-zinc-900 dark:text-zinc-50">{threadId}</h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{repo ?? "Unknown repository"}</p>
        </div>
        <LiveControls
          live={live}
          onToggleLive={() => setLive((v) => !v)}
          onRefresh={refresh}
          lastUpdated={lastUpdated}
          intervalMs={POLL_MS}
        />
      </div>

      {error ? (
        <p className="text-xs text-red-600 dark:text-red-400">
          Last refresh failed ({error.message}). Showing the most recent successful fetch.
        </p>
      ) : null}

      <RunSummaryPanel values={finalValues} pending={pending} />

      <div>
        <SectionLabel>Node timeline</SectionLabel>
        {steps.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">No checkpoints recorded.</p>
        ) : (
          <ol className="mt-3 space-y-3">
            {steps.map((step, i) => (
              <TimelineEntry key={`${step.step}-${step.created_at}`} step={step} previous={steps[i - 1]} />
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
