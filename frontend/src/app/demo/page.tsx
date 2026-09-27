import { DemoRunner } from "@/components/demo-runner";

export default function Page() {
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold text-ink">Live Demo</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Manually dispatch <code className="font-mono">deploy.yml</code> on the demo repo and watch it run — job
          status and both log streams update live, no GitHub tab required.
        </p>
      </div>
      <div className="mt-4 rounded-xl border border-l-4 border-line border-l-accent bg-surface p-4 text-sm text-ink-soft">
        <p className="font-semibold text-ink">Retry the demo a few times</p>
        <p className="mt-1 leading-relaxed">
          The demo test is flaky on purpose, so its result is inconsistent: a run may pass or fail by chance. Only a
          failed run is picked up by the agent and shows up on the Runs page. If Deploy succeeds, press{" "}
          <span className="font-medium text-ink">Run again</span> and repeat until a run fails. It usually takes a
          few tries.
        </p>
      </div>
      <div className="mt-6">
        <DemoRunner />
      </div>
    </>
  );
}
