/**
 * Shapes returned by the backend dashboard API (`backend/src/api/routes/runs.py`).
 * These mirror LangGraph's checkpointed graph state, so every field is optional —
 * a run that crashed mid-graph simply hasn't written the later keys yet.
 */

/** One entry in `rerun_results` — a single test rerun N identical times. */
export type RerunResult = {
  test_id: string;
  attempts: number;
  passed: number;
  failed: number;
};

/**
 * `github_payload.repository` is an object on real GitHub webhooks but a plain
 * string in hand-rolled invocations, so the list endpoint can hand us either.
 */
export type Repository = string | { full_name?: string; name?: string } | null;

/** A row in `GET /api/runs` — one per thread_id (i.e. per CI run). */
export type RunSummary = {
  thread_id: string;
  repository?: Repository;
  is_flaky?: boolean | null;
  fix_applied?: boolean | null;
  retest_passed?: boolean | null;
  document?: string | null;
  updated_at?: string | null;
};

/** The full graph state at one superstep. Keys match `GraphState` in the backend. */
export type GraphValues = {
  github_payload?: Record<string, unknown>;
  logs?: string;
  rerun_results?: RerunResult[];
  is_flaky?: boolean;
  repo_path?: string;
  debug_findings?: string;
  fix_applied?: boolean;
  retest_passed?: boolean;
  document?: string;
  callback_url?: string;
  [key: string]: unknown;
};

/**
 * One superstep from `GET /api/runs/{thread_id}`.
 *
 * `node` is the node that ran to produce this snapshot, and `changed` is the
 * diff against the previous snapshot — i.e. that node's actual conclusion.
 * Both are derived server-side; `node` is null for the bookkeeping checkpoints
 * at the head of every run.
 */
export type RunStep = {
  step: number;
  node: string | null;
  changed: GraphValues;
  next: string[];
  values: GraphValues;
  created_at: string | null;
};

export type RunTimeline = {
  thread_id: string;
  steps: RunStep[];
};
