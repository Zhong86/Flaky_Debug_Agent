import type { Repository, RerunResult, RunStep } from "./types";

/** Unwrap `github_payload.repository`, which may be an object or a bare string. */
export function repoName(repository: Repository | undefined): string | null {
  if (!repository) return null;
  if (typeof repository === "string") return repository;
  return repository.full_name ?? repository.name ?? null;
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return `${Math.max(seconds, 0)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

/** Milliseconds between two supersteps, for showing how long a node took. */
export function stepDuration(step: RunStep, previous: RunStep | undefined): string | null {
  if (!previous?.created_at || !step.created_at) return null;
  const ms = new Date(step.created_at).getTime() - new Date(previous.created_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** Display metadata for each graph node, keyed by the node name LangGraph reports. */
export const NODE_META: Record<string, { label: string; blurb: string }> = {
  __start__: { label: "Input", blurb: "Initial state handed to the graph" },
  check_flaky: { label: "Flaky Check", blurb: "Classifies reruns as flaky or a real failure" },
  clone_repo: { label: "Clone Repo", blurb: "Checks the repository out for the agents to read" },
  debug_agent: { label: "Debug Agent", blurb: "Investigates root cause" },
  code_fix: { label: "Code Fix", blurb: "Applies a patch to the test or source" },
  retest_flaky: { label: "Retest", blurb: "Re-runs the test to confirm the fix" },
  documents: { label: "Documentation", blurb: "Writes the run report to disk" },
  output: { label: "Output", blurb: "Final summary / callback" },
};

export function nodeLabel(node: string | null): string {
  if (!node) return "Checkpoint";
  return NODE_META[node]?.label ?? node;
}

/** Did the suite ever both pass and fail across identical reruns? */
export function isTestFlaky(result: RerunResult): boolean {
  return result.passed > 0 && result.passed < result.attempts;
}

/** `changed` includes housekeeping keys we render in the header instead of the diff. */
const DIFF_HIDDEN_KEYS = new Set(["github_payload", "callback_url"]);

/**
 * Empty values are deliberately NOT filtered out: a node writing `repo_path: ""`
 * means the clone failed, which is exactly the kind of thing this dashboard exists
 * to show. `StateValue` renders the emptiness explicitly instead.
 */
export function visibleDiffEntries(changed: Record<string, unknown>): [string, unknown][] {
  return Object.entries(changed).filter(([key]) => !DIFF_HIDDEN_KEYS.has(key));
}

/**
 * Colour for a step's timeline dot, so the rail can be skimmed for trouble.
 * Orange means "this node ran but wrote something that needs attention" — a failed
 * clone, a skipped fix, a failed retest, or a real (non-flaky) failure.
 */
export function stepTone(step: RunStep): "green" | "orange" | "zinc" {
  if (step.node === null) return "zinc";
  const { repo_path, is_flaky, fix_applied, retest_passed } = step.changed;
  const needsAttention =
    repo_path === "" || is_flaky === false || fix_applied === false || retest_passed === false;
  return needsAttention ? "orange" : "green";
}

export const STATE_KEY_LABELS: Record<string, string> = {
  is_flaky: "Flaky verdict",
  rerun_results: "Rerun results",
  debug_findings: "Findings",
  fix_applied: "Fix applied",
  retest_passed: "Retest passed",
  document: "Report",
  logs: "Logs",
  repo_path: "Repo path",
  callback_url: "Callback URL",
};

export function stateKeyLabel(key: string): string {
  return STATE_KEY_LABELS[key] ?? key;
}
