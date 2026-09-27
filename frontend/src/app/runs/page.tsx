import type { Metadata } from "next";

import { RunsList } from "@/components/runs-list";

export const metadata: Metadata = {
  title: "Runs | Flaky Debug Agent",
};

export default function Page() {
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold text-ink">Runs</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Every checkpointed graph run, newest first. Open one to see what each node concluded.
        </p>
      </div>
      <div className="mt-6">
        <RunsList />
      </div>
    </>
  );
}
