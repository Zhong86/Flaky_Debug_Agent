import { RunDetail } from "@/components/run-detail";

export default async function Page(props: PageProps<"/runs/[thread_id]">) {
  // `thread_id` is the GitHub workflow run id the graph was invoked with.
  const { thread_id } = await props.params;
  return <RunDetail threadId={thread_id} />;
}
