from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/runs", tags=["runs"])


def _run_summary(thread_id: str, channel_values: dict) -> dict:
    return {
        "thread_id": thread_id,
        "repository": channel_values.get("github_payload", {}).get("repository"),
        "is_flaky": channel_values.get("is_flaky"),
        "fix_applied": channel_values.get("fix_applied"),
        "retest_passed": channel_values.get("retest_passed"),
        "document": channel_values.get("document"),
    }


@router.get("")
async def list_runs(request: Request, limit: int = 50):
    """Most recent runs (one row per thread_id), newest first."""
    graph = request.app.state.graph
    seen: dict[str, dict] = {}
    async for checkpoint_tuple in graph.checkpointer.alist(None, limit=limit * 4):
        thread_id = checkpoint_tuple.config["configurable"]["thread_id"]
        if thread_id in seen:
            continue
        summary = _run_summary(thread_id, checkpoint_tuple.checkpoint.get("channel_values", {}))
        summary["updated_at"] = checkpoint_tuple.checkpoint.get("ts")
        seen[thread_id] = summary
        if len(seen) >= limit:
            break
    return {"runs": list(seen.values())}


def _diff(before: dict, after: dict) -> dict:
    """Keys that changed between two consecutive state snapshots — i.e. what a node wrote."""
    return {k: v for k, v in after.items() if before.get(k) != v}


@router.get("/{thread_id}")
async def get_run_timeline(request: Request, thread_id: str):
    """Full step-by-step state history for one run — what each node concluded, in order."""
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    snapshots = [
        {
            "step": snapshot.metadata.get("step"),
            "next": list(snapshot.next),
            "values": snapshot.values,
            "created_at": snapshot.created_at,
        }
        async for snapshot in graph.aget_state_history(config)
    ]
    if not snapshots:
        raise HTTPException(status_code=404, detail=f"No run found for thread_id={thread_id!r}")

    snapshots.reverse()  # LangGraph yields newest-first; the dashboard wants chronological order

    steps = []
    for i, snap in enumerate(snapshots):
        prev = snapshots[i - 1] if i > 0 else None
        steps.append(
            {
                "step": snap["step"],
                # the node that ran between prev and this snapshot
                "node": prev["next"][0] if prev and len(prev["next"]) == 1 else None,
                "changed": _diff(prev["values"], snap["values"]) if prev else snap["values"],
                "next": snap["next"],
                "values": snap["values"],
                "created_at": snap["created_at"],
            }
        )
    return {"thread_id": thread_id, "steps": steps}
