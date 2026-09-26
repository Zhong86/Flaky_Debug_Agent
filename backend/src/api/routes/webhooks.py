# backend/src/api/routes/webhooks.py
from fastapi import APIRouter, Request

from services.github_artifacts import download_rerun_artifacts, parse_junit_results
from services.github_dispatch import trigger_rerun_workflow

router = APIRouter(tags=["webhooks"])

@router.post("/webhooks/github")
async def github_webhook(request: Request):
    payload = await request.json()

    if payload.get("action") != "completed":
        return {"ignored": True}

    run = payload["workflow_run"]

    if run["name"] == "Flaky Rerun":
        # phase B: rerun finished, we now have real data to classify
        xml_files = download_rerun_artifacts(payload["repository"]["full_name"], run["id"])
        rerun_results = parse_junit_results(xml_files)

        initial_state = {
            "github_payload": payload,
            "logs": "",
            "rerun_results": rerun_results,   # ← new field, doesn't exist in GraphState yet
            "callback_url": run["repository"]["full_name"],
        }
        # thread_id groups every checkpoint for this CI run so the dashboard can
        # pull its full node-by-node history back out via /api/runs/{thread_id}
        config = {"configurable": {"thread_id": str(run["id"])}}
        await request.app.state.graph.ainvoke(initial_state, config=config)

    elif run["conclusion"] == "failure":
        # phase A: original test.yml failed, just dispatch the rerun — don't invoke the graph yet
        await trigger_rerun_workflow(payload)

    return {"received": True}