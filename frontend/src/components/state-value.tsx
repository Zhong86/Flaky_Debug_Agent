import type { RerunResult } from "@/lib/types";
import { isTestFlaky } from "@/lib/format";
import { CodeBlock, Mono, Pill, Verdict } from "./ui";

/** Per-test rerun tallies — requirement #1, "which test fails". */
export function RerunResultsTable({ results }: { results: RerunResult[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-md text-left text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-xs tracking-wide text-zinc-500 uppercase dark:border-zinc-800">
            <th className="py-2 pr-4 font-semibold">Test</th>
            <th className="py-2 pr-4 font-semibold">Attempts</th>
            <th className="py-2 pr-4 font-semibold">Passed</th>
            <th className="py-2 pr-4 font-semibold">Failed</th>
            <th className="py-2 font-semibold">Verdict</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/80">
          {results.map((result) => (
            <tr key={result.test_id}>
              <td className="py-2 pr-4 font-mono text-xs break-all text-zinc-800 dark:text-zinc-200">
                {result.test_id}
              </td>
              <td className="py-2 pr-4 tabular-nums text-zinc-600 dark:text-zinc-400">{result.attempts}</td>
              <td className="py-2 pr-4 tabular-nums text-green-600 dark:text-green-400">{result.passed}</td>
              <td className="py-2 pr-4 tabular-nums text-red-600 dark:text-red-400">{result.failed}</td>
              <td className="py-2">
                {isTestFlaky(result) ? (
                  <Pill tone="orange">Flaky</Pill>
                ) : result.passed === 0 ? (
                  <Pill tone="red">Always fails</Pill>
                ) : (
                  <Pill tone="green">Always passes</Pill>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Tri-state booleans get key-specific wording so the timeline reads in plain English. */
const BOOLEAN_LABELS: Record<string, { trueLabel: string; falseLabel: string; trueTone?: "green" | "orange" }> = {
  is_flaky: { trueLabel: "Flaky", falseLabel: "Real failure", trueTone: "orange" },
  fix_applied: { trueLabel: "Fix applied", falseLabel: "No fix applied" },
  retest_passed: { trueLabel: "Retest passed", falseLabel: "Retest failed" },
};

function isRerunResults(name: string, value: unknown): value is RerunResult[] {
  return name === "rerun_results" && Array.isArray(value);
}

/**
 * Renders one graph-state value according to what it actually is — the state is a
 * loose TypedDict, so we dispatch on the key where it matters and fall back to JSON.
 */
export function StateValue({ name, value }: { name: string; value: unknown }) {
  if (isRerunResults(name, value)) {
    return value.length ? <RerunResultsTable results={value} /> : <Pill tone="zinc">No rerun data</Pill>;
  }

  if (typeof value === "boolean") {
    const labels = BOOLEAN_LABELS[name] ?? { trueLabel: "true", falseLabel: "false" };
    return <Verdict value={value} {...labels} />;
  }

  if (typeof value === "number") {
    return <span className="tabular-nums text-zinc-800 dark:text-zinc-200">{value}</span>;
  }

  if (typeof value === "string") {
    if (value === "") {
      // A node that wrote an empty string tried and produced nothing — for repo_path
      // that specifically means `clone_repo` failed, which must not look like success.
      return name === "repo_path" ? (
        <Pill tone="red">Clone failed — no checkout</Pill>
      ) : (
        <Pill tone="zinc">Empty</Pill>
      );
    }
    // Paths and short identifiers read better inline; prose and logs need a block.
    if (value.includes("\n") || value.length > 140) return <CodeBlock>{value}</CodeBlock>;
    if (name === "document" || name === "repo_path" || name === "callback_url") {
      return <Mono>{value}</Mono>;
    }
    return <p className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">{value}</p>;
  }

  if (value === null || value === undefined) return <Pill tone="zinc">Not set</Pill>;

  return <CodeBlock>{JSON.stringify(value, null, 2)}</CodeBlock>;
}
