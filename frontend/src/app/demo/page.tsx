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
      <div className="mt-6">
        <DemoRunner />
      </div>
    </>
  );
}
