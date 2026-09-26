# backend/src/api/routes/webhooks.py
"""Where the user's CI reaches us. See services/flaky_pipeline.py for the two phases.

Both phases only *schedule* their work: artifact downloads, dispatches and the graph
run take far longer than GitHub's 10-second webhook timeout, so they run after the
response as background tasks.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from api.deps import GraphDep, SettingsDep, VerifiedBody
from core.config import Settings
from schemas.github import JUnitIngest, WebhookAck, WorkflowRunEvent
from services import flaky_pipeline
from services.github_dispatch import RERUN_WORKFLOW_NAME, parse_rerun_title

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _parse[Model: BaseModel](model: type[Model], body: bytes) -> Model:
    # Bodies are parsed by hand, after the signature check, instead of as a FastAPI
    # body parameter — so unsigned requests never reach validation.
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _require[T](dependency: T | None, what: str) -> T:
    if dependency is None or dependency == "":
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{what} is not configured")
    return dependency


def _require_token(settings: Settings) -> None:
    _require(settings.github_token, "GITHUB_TOKEN")


def _ignored(reason: str, thread_id: str | None = None) -> WebhookAck:
    return WebhookAck(action="ignored", reason=reason, thread_id=thread_id)


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    body: VerifiedBody,
    settings: SettingsDep,
    graph: GraphDep,
    background_tasks: BackgroundTasks,
    x_github_event: Annotated[str | None, Header()] = None,
) -> WebhookAck:
    """Repo webhook. Only completed `workflow_run` events do anything."""
    if x_github_event != "workflow_run":
        return _ignored(f"event {x_github_event!r} is not handled")

    event = _parse(WorkflowRunEvent, body)
    if event.action != "completed":
        return _ignored(f"workflow_run action {event.action!r} is not handled")
    run = event.workflow_run

    if run.name == RERUN_WORKFLOW_NAME:
        # phase B: rerun finished, we now have real data to classify
        title = parse_rerun_title(run.display_title)
        if title is None:
            return _ignored("rerun's run-name doesn't follow the flaky-rerun.yml contract")
        if title.purpose != "detect":
            # retest_flaky dispatched this one and is polling it itself; analysing it
            # here would start a new graph run that retests again, forever.
            return _ignored("retest runs are awaited by the retest_flaky node")
        if title.original_run_id is None:
            return _ignored("detect rerun has no original run id")

        thread_id = str(title.original_run_id)
        graph = _require(graph, "Graph checkpointer")
        _require_token(settings)
        if await flaky_pipeline.thread_exists(graph, thread_id):
            return _ignored("this run was already analyzed", thread_id)
        if not flaky_pipeline.claim_analysis(thread_id):
            return _ignored("analysis already scheduled for this run", thread_id)
        background_tasks.add_task(flaky_pipeline.analyze_rerun, graph, event, title.original_run_id)
        return WebhookAck(action="analysis_scheduled", thread_id=thread_id)

    # phase A: original test workflow failed, just dispatch the rerun — don't invoke
    # the graph yet
    if reason := flaky_pipeline.rerun_skip_reason(event, settings):
        return _ignored(reason)
    _require_token(settings)
    if not flaky_pipeline.claim_rerun(event):
        return _ignored("rerun already scheduled for this run attempt", str(run.id))
    background_tasks.add_task(flaky_pipeline.start_rerun, event)
    return WebhookAck(action="rerun_scheduled", thread_id=str(run.id))


@router.post(
    "/junit",
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": JUnitIngest.model_json_schema()}},
        }
    },
)
async def junit_ingest(
    body: VerifiedBody, graph: GraphDep, background_tasks: BackgroundTasks
) -> WebhookAck:
    """Hand in JUnit XML reports directly, signed like a GitHub webhook.

    Skips the GitHub rerun round-trip: for local testing, and for CI systems other
    than GitHub Actions. `reports` maps attempt number (0 = original run) to XML strings.
    """
    ingest = _parse(JUnitIngest, body)
    graph = _require(graph, "Graph checkpointer")
    if await flaky_pipeline.thread_exists(graph, ingest.run_id):
        return _ignored("this run was already analyzed", ingest.run_id)
    if not flaky_pipeline.claim_analysis(ingest.run_id):
        return _ignored("analysis already scheduled for this run", ingest.run_id)
    background_tasks.add_task(
        flaky_pipeline.analyze_reports,
        graph,
        thread_id=ingest.run_id,
        github_payload=flaky_pipeline.ingest_payload(ingest),
        callback_url=ingest.run_url,
        reports=ingest.reports,
    )
    return WebhookAck(action="analysis_scheduled", thread_id=ingest.run_id)
