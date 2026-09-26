"""Where the user's CI reaches us. See services/flaky_pipeline.py for the two phases."""

from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

from api.deps import GitHubAppDep, GraphDep, SettingsDep, VerifiedBody
from schemas.github import JUnitIngest, WebhookAck, WorkflowRunEvent
from services import flaky_pipeline

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _parse[Model: BaseModel](model: type[Model], body: bytes) -> Model:
    # Bodies are parsed by hand, after the signature check, instead of as a FastAPI
    # body parameter — so unsigned requests never reach validation.
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc


def _require[T](dependency: T | None, what: str) -> T:
    if dependency is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{what} is not configured")
    return dependency


def _ignored(reason: str, thread_id: str | None = None) -> WebhookAck:
    return WebhookAck(action="ignored", reason=reason, thread_id=thread_id)


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    body: VerifiedBody,
    settings: SettingsDep,
    graph: GraphDep,
    github_app: GitHubAppDep,
    background_tasks: BackgroundTasks,
    x_github_event: Annotated[str | None, Header()] = None,
) -> WebhookAck:
    """GitHub App webhook. Only completed `workflow_run` events do anything."""
    if x_github_event != "workflow_run":
        return _ignored(f"event {x_github_event!r} is not handled")

    event = _parse(WorkflowRunEvent, body)
    if event.action != "completed":
        return _ignored(f"workflow_run action {event.action!r} is not handled")
    run = event.workflow_run

    if run.name == settings.rerun_workflow_name:
        # phase B: rerun finished, we now have real data to classify. Collecting the
        # artifacts and running the graph takes minutes, far past GitHub's 10s webhook
        # timeout, so it runs after the response.
        original_id = flaky_pipeline.original_run_id(run)
        if original_id is None:
            return _ignored("rerun's run-name has no '#<original_run_id>'")
        if event.installation is None:
            return _ignored("payload has no GitHub App installation")
        thread_id = str(original_id)
        graph = _require(graph, "Graph checkpointer")
        if await flaky_pipeline.thread_exists(graph, thread_id):
            return _ignored("this run was already analyzed", thread_id)
        background_tasks.add_task(
            flaky_pipeline.analyze_rerun,
            graph,
            _require(github_app, "GitHub App"),
            event,
            original_id,
            settings,
        )
        return WebhookAck(action="analysis_scheduled", thread_id=thread_id)

    # phase A: original test workflow failed, just dispatch the rerun — don't invoke the
    # graph yet. Done inline: it's one API call, and a failure here should mark the
    # delivery as failed in GitHub so it can be redelivered.
    if reason := flaky_pipeline.rerun_skip_reason(event, settings):
        return _ignored(reason)
    try:
        dispatched = await flaky_pipeline.dispatch_rerun(
            _require(github_app, "GitHub App"), event, settings
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"GitHub refused the rerun dispatch ({exc.response.status_code}): "
            f"{exc.response.text[:300]}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"GitHub unreachable: {exc}") from exc
    if not dispatched:
        return _ignored("rerun already dispatched for this run attempt", str(run.id))
    return WebhookAck(action="rerun_dispatched", thread_id=str(run.id))


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
    background_tasks.add_task(
        flaky_pipeline.analyze_reports,
        graph,
        thread_id=ingest.run_id,
        github_payload=flaky_pipeline.ingest_payload(ingest),
        callback_url=ingest.run_url,
        reports=ingest.reports,
    )
    return WebhookAck(action="analysis_scheduled", thread_id=ingest.run_id)
