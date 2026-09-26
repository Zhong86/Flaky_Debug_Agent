"""The two webhook phases around the LangGraph run.

Phase A — a watched CI workflow failed: dispatch the "Flaky Rerun" workflow in the
          user's repo. The graph is not invoked yet; there's nothing to classify.
Phase B — that rerun completed: collect its JUnit XML (plus the original run's, as
          attempt 0), turn it into `rerun_results` and invoke the graph. The thread_id
          is the original run id, so the dashboard shows one row per failed CI run.
"""

import logging
import re
from collections import OrderedDict
from collections.abc import Hashable, Mapping, Sequence
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from core.config import Settings
from graph.state import GraphState
from schemas.github import JUnitIngest, WorkflowRun, WorkflowRunEvent
from services import github_artifacts
from services.github_app import GitHubApp
from services.junit import failure_log, parse_junit_results

logger = logging.getLogger(__name__)

# Our rerun sets `run-name: "Flaky Rerun #<original_run_id>"`; the webhook only
# exposes it as `display_title`, which is how phase B finds the original run.
_ORIGINAL_RUN_ID = re.compile(r"#(\d+)")


class _RecentKeys:
    """Bounded memory of recently seen keys, to drop GitHub's duplicate deliveries."""

    def __init__(self, maxlen: int = 1024) -> None:
        self._keys: OrderedDict[Hashable, None] = OrderedDict()
        self._maxlen = maxlen

    def add(self, key: Hashable) -> bool:
        """Remember *key*; False if it was already there."""
        if key in self._keys:
            return False
        self._keys[key] = None
        if len(self._keys) > self._maxlen:
            self._keys.popitem(last=False)
        return True

    def discard(self, key: Hashable) -> None:
        self._keys.pop(key, None)

    def clear(self) -> None:
        self._keys.clear()


dispatched_runs = _RecentKeys()


# --- Phase A ------------------------------------------------------------------------


def rerun_skip_reason(event: WorkflowRunEvent, settings: Settings) -> str | None:
    """Why a completed workflow run should NOT get a flaky rerun, or None to go ahead."""
    run = event.workflow_run
    if run.conclusion != "failure":
        return f"conclusion is {run.conclusion!r}, not 'failure'"
    if settings.watched_workflows and run.name not in settings.watched_workflows:
        return f"workflow {run.name!r} is not in WATCHED_WORKFLOWS"
    if run.head_repository and run.head_repository.full_name != event.repository.full_name:
        return "run comes from a fork, whose commits the rerun can't dispatch against"
    if event.installation is None:
        return "payload has no GitHub App installation"
    return None


async def dispatch_rerun(app: GitHubApp, event: WorkflowRunEvent, settings: Settings) -> bool:
    """Dispatch the Flaky Rerun for a failed run. False if it was already dispatched."""
    run = event.workflow_run
    key = (event.repository.full_name, run.id, run.run_attempt)
    if not dispatched_runs.add(key):
        return False
    try:
        async with await app.installation_client(event.installation.id) as client:
            # Always dispatch on the default branch — workflow_dispatch needs the workflow
            # file there — and let the rerun check out `head_sha` itself.
            await github_artifacts.dispatch_rerun(
                client,
                repository=event.repository.full_name,
                ref=event.repository.default_branch,
                workflow_file=settings.rerun_workflow_file,
                run=run,
                attempts=settings.rerun_attempts,
            )
    except Exception:
        dispatched_runs.discard(key)  # let GitHub's redelivery try again
        raise
    return True


# --- Phase B ------------------------------------------------------------------------


def original_run_id(rerun: WorkflowRun) -> int | None:
    match = _ORIGINAL_RUN_ID.search(rerun.display_title)
    return int(match.group(1)) if match else None


async def thread_exists(graph: CompiledStateGraph, thread_id: str) -> bool:
    if graph.checkpointer is None:
        return False
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    return bool(snapshot.values)


def run_payload(
    repository: str,
    run: WorkflowRun,
    rerun: WorkflowRun | None = None,
    installation_id: int | None = None,
) -> dict[str, Any]:
    """The `github_payload` the graph sees: a flat, token-free summary of the CI run.

    `repository` is the `owner/repo` string that `clone_repo` and the dashboard expect.
    """
    return {
        "repository": repository,
        "branch": run.head_branch or "",
        "head_sha": run.head_sha,
        "run_id": str(run.id),
        "run_attempt": run.run_attempt,
        "run_url": run.html_url,
        "workflow": run.name,
        "event": run.event,
        "pull_requests": [pr.number for pr in run.pull_requests],
        "rerun_run_id": str(rerun.id) if rerun else None,
        "rerun_run_url": rerun.html_url if rerun else None,
        "installation_id": installation_id,
    }


def ingest_payload(ingest: JUnitIngest) -> dict[str, Any]:
    return {
        "repository": ingest.repository,
        "branch": ingest.branch,
        "head_sha": ingest.head_sha,
        "run_id": ingest.run_id,
        "run_url": ingest.run_url,
        "source": "junit-ingest",
    }


async def analyze_reports(
    graph: CompiledStateGraph,
    *,
    thread_id: str,
    github_payload: dict[str, Any],
    callback_url: str,
    reports: Mapping[int, Sequence[bytes | str]],
) -> None:
    """Classify the JUnit reports and run the graph. Meant to run as a background task."""
    try:
        if not any(reports.values()):
            logger.error(
                "No JUnit reports for thread %s — does the rerun upload '*-attempt-<n>' artifacts?",
                thread_id,
            )
            return

        rerun_results = parse_junit_results(reports)
        initial_state: GraphState = {
            "github_payload": github_payload,
            "logs": failure_log(rerun_results),
            "rerun_results": rerun_results,
            "is_flaky": False,
            "repo_path": "",
            "debug_findings": "",
            "fix_applied": False,
            "retest_passed": False,
            "document": "",
            "callback_url": callback_url,
        }
        # thread_id groups every checkpoint for this CI run so the dashboard can
        # pull its full node-by-node history back out via /api/runs/{thread_id}
        await graph.ainvoke(initial_state, config={"configurable": {"thread_id": thread_id}})
    except Exception:
        logger.exception("Graph run failed for thread %s", thread_id)


async def analyze_rerun(
    graph: CompiledStateGraph,
    app: GitHubApp,
    event: WorkflowRunEvent,
    original_id: int,
    settings: Settings,
) -> None:
    """Phase B background task: fetch the rerun's evidence, then run the graph."""
    repository = event.repository.full_name
    try:
        async with await app.installation_client(event.installation.id) as client:
            original = await github_artifacts.get_run(client, repository, original_id)
            reports = await github_artifacts.download_rerun_artifacts(
                client,
                repository,
                event.workflow_run.id,
                prefix=settings.junit_artifact_prefix,
                max_bytes=settings.max_artifact_bytes,
            )
            # The failing CI run's own report, if it uploaded one, is attempt 0 — it's
            # the only evidence when a test failed in CI but passes every rerun.
            original_reports = await github_artifacts.download_rerun_artifacts(
                client,
                repository,
                original_id,
                prefix=settings.junit_artifact_prefix,
                max_bytes=settings.max_artifact_bytes,
                attempt_for_all=0,
            )
    except Exception:
        logger.exception("Collecting rerun artifacts failed for %s run %s", repository, original_id)
        return

    for attempt, files in original_reports.items():
        reports.setdefault(attempt, []).extend(files)

    await analyze_reports(
        graph,
        thread_id=str(original_id),
        github_payload=run_payload(
            repository, original, rerun=event.workflow_run, installation_id=event.installation.id
        ),
        callback_url=original.html_url,
        reports=reports,
    )
