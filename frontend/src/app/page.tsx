import { RunsList } from "@/components/runs-list";

export default function Page() {
  return (
    <>
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">Runs</h1>
        <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
          Every checkpointed graph run, newest first. Open one to see what each node concluded.
        </p>
      </div>
      <div className="mt-6">
        <RunsList />
      </div>
    </>
  );
}
