"""The two webhook phases around the LangGraph run.

Phase A — a watched CI workflow failed: read its JUnit artifact for the failing
          tests and dispatch flaky-rerun.yml ("detect") on them. The graph is not
          invoked yet; there's nothing to classify.
Phase B — that detect rerun completed: collect its JUnit XML (plus the original
          run's, as attempt 0), turn it into `rerun_results` and invoke the graph.
          The thread_id is the original run id, so the dashboard shows one row per
          failed CI run.
Retest runs dispatched by the graph's own retest_flaky node are never analysed
here — that node waits for them itself.
"""

import logging
from collections import OrderedDict
from collections.abc import Hashable
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from core.config import Settings
from graph.state import GraphState
from schemas.github import JUnitIngest, WorkflowRun, WorkflowRunEvent
from services import github_artifacts, github_dispatch
from services.junit import Reports, failure_log, parse_junit_results

logger = logging.getLogger(__name__)


class _RecentKeys:
    """Bounded memory of recently claimed work, to drop GitHub's duplicate deliveries."""

    def __init__(self, maxlen: int = 1024) -> None:
        self._keys: OrderedDict[Hashable, None] = OrderedDict()
        self._maxlen = maxlen

    def add(self, key: Hashable) -> bool:
        """Claim *key*; False if it was already claimed."""
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


claimed = _RecentKeys()


def _rerun_key(event: WorkflowRunEvent) -> tuple:
    run = event.workflow_run
    return ("rerun", event.repository.full_name, run.id, run.run_attempt)


def _analysis_key(thread_id: str) -> tuple:
    return ("analysis", thread_id)


def _installation_id(event: WorkflowRunEvent) -> int | None:
    return event.installation.id if event.installation else None


# --- Phase A ------------------------------------------------------------------------


def rerun_skip_reason(event: WorkflowRunEvent, settings: Settings) -> str | None:
    """Why a completed workflow run should NOT get a flaky rerun, or None to go ahead."""
    run = event.workflow_run
    if run.conclusion != "failure":
        return f"conclusion is {run.conclusion!r}, not 'failure'"
    if settings.watched_workflows and run.name not in settings.watched_workflows:
        return f"workflow {run.name!r} is not in WATCHED_WORKFLOWS"
    if run.head_repository and run.head_repository.full_name != event.repository.full_name:
        return "run comes from a fork; its commit isn't in this repo"
    return None


def claim_rerun(event: WorkflowRunEvent) -> bool:
    """Reserve phase A for this run attempt; False if a delivery already did."""
    return claimed.add(_rerun_key(event))


async def start_rerun(event: WorkflowRunEvent) -> None:
    """Phase A background task: dispatch flaky-rerun.yml on the run's failing tests."""
    repo = event.repository.full_name
    run = event.workflow_run
    try:
        test_ids = await github_dispatch.trigger_rerun_workflow(
            repo, run, event.repository.default_branch, installation_id=_installation_id(event)
        )
    except Exception:
        claimed.discard(_rerun_key(event))  # let GitHub's redelivery try again
        logger.exception("Dispatching the flaky rerun failed for %s run %s", repo, run.id)
        return
    if test_ids:
        logger.info(
            "Dispatched flaky rerun of %d test(s) for %s run %s", len(test_ids), repo, run.id
        )
    else:
        logger.info(
            "%s run %s uploaded no JUnit XML with failures — nothing to rerun", repo, run.id
        )


# --- Phase B ------------------------------------------------------------------------


async def thread_exists(graph: CompiledStateGraph, thread_id: str) -> bool:
    if graph.checkpointer is None:
        return False
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    return bool(snapshot.values)


def claim_analysis(thread_id: str) -> bool:
    """Reserve the graph run for this thread; False if a delivery already did."""
    return claimed.add(_analysis_key(thread_id))


def run_payload(repository: str, run: WorkflowRun, rerun: WorkflowRun | None = None) -> dict:
    """The `github_payload` the graph sees: a flat, token-free summary of the failed CI run.

    `repository` is the `owner/repo` string clone_repo and the dashboard expect, and
    `branch` / `sha` are what clone_repo and retest_flaky read.
    """
    return {
        "repository": repository,
        "branch": run.head_branch or "",
        "sha": run.head_sha,
        "run_id": str(run.id),
        "run_attempt": run.run_attempt,
        "run_url": run.html_url,
        "workflow": run.name,
        "event": run.event,
        "pull_requests": [pr.number for pr in run.pull_requests],
        "rerun_run_id": str(rerun.id) if rerun else None,
        "rerun_run_url": rerun.html_url if rerun else None,
    }


def ingest_payload(ingest: JUnitIngest) -> dict:
    return {
        "repository": ingest.repository,
        "branch": ingest.branch,
        "sha": ingest.sha,
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
    reports: Reports,
    installation_id: int | None = None,
) -> None:
    """Classify the JUnit reports and run the graph. Meant to run as a background task."""
    try:
        if not any(reports.values()):
            logger.error(
                "No JUnit reports for thread %s — does the rerun upload "
                "'rerun-attempt-<n>' artifacts?",
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
            "fix_branch": "",
            "fix_sha": "",
            "retest_passed": False,
            "document": "",
            "callback_url": callback_url,
            "installation_id": installation_id,
        }
        # thread_id groups every checkpoint for this CI run so the dashboard can
        # pull its full node-by-node history back out via /api/runs/{thread_id}
        await graph.ainvoke(initial_state, config={"configurable": {"thread_id": thread_id}})
    except Exception:
        claimed.discard(_analysis_key(thread_id))
        logger.exception("Graph run failed for thread %s", thread_id)


async def analyze_rerun(
    graph: CompiledStateGraph, event: WorkflowRunEvent, original_id: int
) -> None:
    """Phase B background task: fetch the detect rerun's evidence, then run the graph."""
    repo = event.repository.full_name
    thread_id = str(original_id)
    installation_id = _installation_id(event)
    try:
        original = WorkflowRun.model_validate(
            await github_dispatch.get_run(repo, original_id, installation_id=installation_id)
        )
        reports = await github_artifacts.download_rerun_artifacts(
            repo, event.workflow_run.id, installation_id=installation_id
        )
        # The failing CI run's own report is attempt 0: without it, a test that failed
        # in CI but passed every rerun would read as "never failed", not flaky.
        original_reports = await github_artifacts.download_run_artifacts(
            repo, original_id, installation_id=installation_id
        )
    except Exception:
        claimed.discard(_analysis_key(thread_id))
        logger.exception("Collecting rerun artifacts failed for %s run %s", repo, original_id)
        return

    if original_attempt := original_reports.get(0):
        reports.setdefault(0, []).extend(original_attempt)

    await analyze_reports(
        graph,
        thread_id=thread_id,
        github_payload=run_payload(repo, original, rerun=event.workflow_run),
        callback_url=original.html_url,
        reports=reports,
        installation_id=installation_id,
    )
