import { DemoRunner } from "@/components/demo-runner";

export default function Page() {
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">Live Demo</h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
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
