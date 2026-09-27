import Link from "next/link";

import { Card } from "@/components/ui";

const STEPS = [
  {
    title: "Detect",
    body: "A watched GitHub Actions workflow fails. The agent reads the failing tests from the run's JUnit report.",
  },
  {
    title: "Rerun",
    body: "Flaky Rerun repeats only those tests several times in parallel, each attempt on a fresh runner.",
  },
  {
    title: "Classify",
    body: "A test that both passed and failed across identical reruns is flaky. One that always fails is a real failure.",
  },
  {
    title: "Investigate and fix",
    body: "IBM Bob reads the recent diff and the test source, then pushes a minimal fix to a separate flaky-fix branch.",
  },
  {
    title: "Retest and report",
    body: "The fix branch is rerun the same way to verify it, and a markdown report of the whole run is written.",
  },
];

const FRAMEWORKS = ["pytest", "Jest", "Vitest", "Go", "Maven / Gradle", "RSpec", ".NET"];

export default function Page() {
  return (
    <div className="space-y-14 py-4">
      <section className="max-w-3xl">
        <p className="text-xs font-semibold tracking-widest text-accent uppercase">CI flaky-test agent</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight text-ink sm:text-5xl">Flaky Debug Agent</h1>
        <p className="mt-5 text-base leading-relaxed text-ink-soft sm:text-lg">
          Watches your GitHub Actions pipeline. When a test fails, it reruns it several times in parallel on fresh
          runners to tell a flaky test from a real failure. For flaky tests, IBM Bob investigates the root cause,
          applies a minimal fix on a separate branch, verifies it with a retest and writes a report.
        </p>
        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link
            href="/runs"
            className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            View runs
          </Link>
          <Link
            href="/demo"
            className="rounded-lg border border-line-strong px-4 py-2 text-sm font-medium text-ink-soft transition-colors hover:border-accent hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Watch the live demo
          </Link>
        </div>
      </section>

      <section>
        <h2 className="text-xs font-semibold tracking-wide text-ink-faint uppercase">How it works</h2>
        <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {STEPS.map((step, index) => (
            <li key={step.title}>
              <Card className="h-full p-4">
                <p className="font-mono text-sm font-semibold text-accent">{String(index + 1).padStart(2, "0")}</p>
                <h3 className="mt-2 font-semibold text-ink">{step.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-muted">{step.body}</p>
              </Card>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className="text-xs font-semibold tracking-wide text-ink-faint uppercase">Works with</h2>
        <ul className="mt-3 flex flex-wrap gap-2">
          {FRAMEWORKS.map((framework) => (
            <li
              key={framework}
              className="rounded-md border border-line bg-surface px-2.5 py-1 font-mono text-xs text-ink-soft"
            >
              {framework}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
