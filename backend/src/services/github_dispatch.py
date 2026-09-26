"""Dispatching flaky-rerun.yml on a target repo and waiting for the result.

workflow_dispatch responds with 204 and no run ID, so finding the run we just
created means listing recent runs and matching by timestamp — see
find_dispatched_run below.
"""

import asyncio
import json
from datetime import datetime, timezone

import httpx

from core.config import get_settings
from services.github_artifacts import download_run_artifacts, parse_failed_test_ids

RERUN_WORKFLOW_FILE = "flaky-rerun.yml"


def _headers() -> dict:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
    }


async def dispatch_workflow(repo: str, workflow_file: str, ref: str, inputs: dict) -> str:
    """Kick off a workflow_dispatch run. Returns the ISO timestamp used to find it afterward."""
    dispatched_at = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(base_url=get_settings().github_api_base, timeout=30) as client:
        resp = await client.post(
            f"/repos/{repo}/actions/workflows/{workflow_file}/dispatches",
            headers=_headers(),
            json={"ref": ref, "inputs": inputs},
        )
        resp.raise_for_status()
    return dispatched_at


async def find_dispatched_run(
    repo: str, workflow_file: str, dispatched_after: str, retries: int = 5, delay: float = 2.0
) -> int:
    """Poll the runs list for the run we just dispatched (no run ID comes back from dispatch itself)."""
    async with httpx.AsyncClient(base_url=get_settings().github_api_base, timeout=30) as client:
        for _ in range(retries):
            resp = await client.get(
                f"/repos/{repo}/actions/workflows/{workflow_file}/runs",
                headers=_headers(),
                params={"event": "workflow_dispatch"},
            )
            resp.raise_for_status()
            for run in resp.json()["workflow_runs"]:
                if run["created_at"] > dispatched_after:
                    return run["id"]
            await asyncio.sleep(delay)
    raise TimeoutError(f"Dispatched run for {workflow_file} on {repo} never appeared")


async def wait_for_run_completion(repo: str, run_id: int, timeout: int = 300, interval: int = 10) -> str:
    """Block (via polling) until the run finishes. Returns its conclusion (success/failure/...)."""
    async with httpx.AsyncClient(base_url=get_settings().github_api_base, timeout=30) as client:
        elapsed = 0
        while elapsed < timeout:
            resp = await client.get(f"/repos/{repo}/actions/runs/{run_id}", headers=_headers())
            resp.raise_for_status()
            run = resp.json()
            if run["status"] == "completed":
                return run["conclusion"]
            await asyncio.sleep(interval)
            elapsed += interval
    raise TimeoutError(f"Run {run_id} on {repo} did not complete within {timeout}s")


async def rerun_and_wait(
    repo: str, ref: str, sha: str, test_ids: list[str], framework: str = "pytest", attempts: int = 5
) -> list[dict]:
    """Dispatch flaky-rerun.yml, wait for it, and return the parsed per-test results."""
    from services.github_artifacts import parse_junit_results  # avoid a module-level cycle w/ this file

    dispatched_at = await dispatch_workflow(
        repo,
        RERUN_WORKFLOW_FILE,
        ref=ref,
        inputs={
            "sha": sha,
            "test_ids": json.dumps(test_ids),
            "framework": framework,
            "attempts": str(attempts),
        },
    )
    run_id = await find_dispatched_run(repo, RERUN_WORKFLOW_FILE, dispatched_at)
    await wait_for_run_completion(repo, run_id)
    xml_paths = await download_run_artifacts(repo, run_id)
    return parse_junit_results(xml_paths)


async def trigger_rerun_workflow(payload: dict) -> None:
    """Phase A: test.yml just failed — pull its failing test IDs and dispatch the targeted rerun.

    Assumes test.yml already uploads its own JUnit XML as a build artifact
    (see the near-zero-touch onboarding path) — no artifact, no test IDs to target.
    """
    run = payload["workflow_run"]
    repo = payload["repository"]["full_name"]

    xml_paths = await download_run_artifacts(repo, run["id"])
    failed_test_ids = parse_failed_test_ids(xml_paths)
    if not failed_test_ids:
        return

    await dispatch_workflow(
        repo,
        RERUN_WORKFLOW_FILE,
        ref=run["head_branch"],
        inputs={
            "sha": run["head_sha"],
            "test_ids": json.dumps(failed_test_ids),
            "framework": "pytest",  # TODO: look up per-repo framework from the install config
            "attempts": "5",
        },
    )
