"""Dispatching flaky-rerun.yml on a target repo and waiting for the result.

workflow_dispatch responds with 204 and no run ID, so finding the run we just
created means listing recent runs and matching them — see find_dispatched_run
below. flaky-rerun.yml's `run-name` (rerun_title) makes that match exact, and
also tells the webhook which reruns it should analyse ("detect") and which ones
retest_flaky is already waiting on itself ("retest").
"""

import asyncio
import base64
import json
import re
from datetime import UTC, datetime
from typing import Literal, NamedTuple

from core.config import get_settings
from schemas.github import WorkflowRun
from services.github_artifacts import (
    download_rerun_artifacts,
    download_run_artifacts,
    parse_failed_test_ids,
    parse_junit_results,
)
from services.github_client import github_client

# Unambiguous root-level marker files → the framework input flaky-rerun.yml expects
# (backend/templates/flaky-rerun.yml). Checked in order; first match wins.
_FRAMEWORK_MARKERS: tuple[tuple[str, str], ...] = (
    ("go.mod", "go"),
    ("pom.xml", "maven"),
    ("Gemfile", "rspec"),
    ("requirements.txt", "pytest"),
    ("pyproject.toml", "pytest"),
    ("setup.py", "pytest"),
    ("setup.cfg", "pytest"),
    ("Pipfile", "pytest"),
)

RERUN_WORKFLOW_FILE = "flaky-rerun.yml"
RERUN_WORKFLOW_NAME = "Flaky Rerun"

Purpose = Literal["detect", "retest"]

# Must mirror `run-name` in backend/templates/flaky-rerun.yml.
_RERUN_TITLE = re.compile(
    rf"^{RERUN_WORKFLOW_NAME} \((?P<purpose>detect|retest)\) #(?P<original_run_id>\d*) @ (?P<sha>\S+)$"
)


class RerunTitle(NamedTuple):
    purpose: Purpose
    original_run_id: int | None
    sha: str


def rerun_title(purpose: Purpose, original_run_id: str, sha: str) -> str:
    """The run-name flaky-rerun.yml gives itself for these inputs."""
    return f"{RERUN_WORKFLOW_NAME} ({purpose}) #{original_run_id} @ {sha}"


def parse_rerun_title(title: str) -> RerunTitle | None:
    """Read back a flaky-rerun.yml run-name; None if the run doesn't follow the contract."""
    match = _RERUN_TITLE.match(title)
    if not match:
        return None
    original = match["original_run_id"]
    return RerunTitle(match["purpose"], int(original) if original else None, match["sha"])


async def dispatch_workflow(
    repo: str, workflow_file: str, ref: str, inputs: dict, installation_id: int | None = None
) -> str:
    """Kick off a workflow_dispatch run. Returns the ISO timestamp used to find it afterward."""
    dispatched_at = datetime.now(UTC).isoformat()
    async with await github_client(installation_id) as client:
        resp = await client.post(
            f"/repos/{repo}/actions/workflows/{workflow_file}/dispatches",
            json={"ref": ref, "inputs": inputs},
        )
        resp.raise_for_status()
    return dispatched_at


async def find_dispatched_run(
    repo: str,
    workflow_file: str,
    dispatched_after: str,
    display_title: str | None = None,
    retries: int = 5,
    delay: float = 2.0,
    installation_id: int | None = None,
) -> int:
    """Poll the runs list for the run we just dispatched (no run ID comes back from dispatch itself).

    With *display_title*, only a run carrying exactly that run-name matches — so a
    concurrent dispatch of the same workflow can't be mistaken for ours.
    """
    async with await github_client(installation_id) as client:
        for _ in range(retries):
            resp = await client.get(
                f"/repos/{repo}/actions/workflows/{workflow_file}/runs",
                params={"event": "workflow_dispatch"},
            )
            resp.raise_for_status()
            for run in resp.json()["workflow_runs"]:
                if run["created_at"] > dispatched_after and (
                    display_title is None or run.get("display_title") == display_title
                ):
                    return run["id"]
            await asyncio.sleep(delay)
    raise TimeoutError(f"Dispatched run for {workflow_file} on {repo} never appeared")


async def get_run(repo: str, run_id: int, installation_id: int | None = None) -> dict:
    async with await github_client(installation_id) as client:
        resp = await client.get(f"/repos/{repo}/actions/runs/{run_id}")
        resp.raise_for_status()
        return resp.json()


async def wait_for_run_completion(
    repo: str,
    run_id: int,
    timeout: int = 300,
    interval: int = 10,
    installation_id: int | None = None,
) -> str:
    """Block (via polling) until the run finishes. Returns its conclusion (success/failure/...)."""
    elapsed = 0
    while elapsed < timeout:
        run = await get_run(repo, run_id, installation_id)
        if run["status"] == "completed":
            return run["conclusion"]
        await asyncio.sleep(interval)
        elapsed += interval
    raise TimeoutError(f"Run {run_id} on {repo} did not complete within {timeout}s")


async def rerun_and_wait(
    repo: str,
    ref: str,
    sha: str,
    test_ids: list[str],
    framework: str = "pytest",
    attempts: int | None = None,
    original_run_id: str = "",
    installation_id: int | None = None,
) -> list[dict]:
    """Dispatch flaky-rerun.yml as a retest, wait for it, and return the parsed per-test results.

    The run is tagged `retest`, so the webhook leaves it alone instead of starting
    a new analysis from it.
    """
    purpose: Purpose = "retest"
    dispatched_at = await dispatch_workflow(
        repo,
        RERUN_WORKFLOW_FILE,
        ref=ref,
        inputs={
            "sha": sha,
            "test_ids": json.dumps(test_ids),
            "framework": framework,
            "attempts": str(attempts or get_settings().rerun_attempts),
            "original_run_id": original_run_id,
            "purpose": purpose,
        },
        installation_id=installation_id,
    )
    run_id = await find_dispatched_run(
        repo,
        RERUN_WORKFLOW_FILE,
        dispatched_at,
        display_title=rerun_title(purpose, original_run_id, sha),
        installation_id=installation_id,
    )
    await wait_for_run_completion(repo, run_id, installation_id=installation_id)
    return parse_junit_results(await download_rerun_artifacts(repo, run_id, installation_id=installation_id))


async def detect_framework(repo: str, ref: str, installation_id: int | None = None) -> str:
    """Best-effort framework guess for flaky-rerun.yml's `framework` input.

    There's no persisted per-repo config to read yet, so this looks at the repo's
    root files instead: unambiguous markers (go.mod, pom.xml, Gemfile, ...) settle
    it outright; `package.json` needs its own dependency list to tell jest from
    vitest. Falls back to "pytest" — flaky-rerun.yml's own default — when the repo
    listing is unreadable or nothing matches, rather than failing the dispatch.
    """
    async with await github_client(installation_id) as client:
        resp = await client.get(f"/repos/{repo}/contents", params={"ref": ref})
        if resp.status_code != 200:
            return "pytest"
        names = {entry["name"] for entry in resp.json() if entry.get("type") == "file"}

        for marker, framework in _FRAMEWORK_MARKERS:
            if marker in names:
                return framework
        if any(name.endswith((".csproj", ".sln")) for name in names):
            return "dotnet"
        if "package.json" in names:
            pkg_resp = await client.get(f"/repos/{repo}/contents/package.json", params={"ref": ref})
            if pkg_resp.status_code == 200:
                pkg = json.loads(base64.b64decode(pkg_resp.json()["content"]))
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "vitest" in deps:
                    return "vitest"
                return "jest"
    return "pytest"


async def trigger_rerun_workflow(
    repo: str, run: WorkflowRun, default_branch: str, installation_id: int | None = None
) -> list[str]:
    """Phase A: a CI run just failed — pull its failing test IDs and dispatch the targeted rerun.

    Assumes the failing workflow uploads its own JUnit XML as a build artifact
    (see the near-zero-touch onboarding path) — no artifact, no test IDs to target.
    Dispatches on the default branch, where flaky-rerun.yml is guaranteed to exist
    (and fork branches aren't needed); the workflow checks out the failing `sha` itself.
    Returns the test IDs it asked to rerun (empty if it dispatched nothing).
    """
    failed_test_ids = parse_failed_test_ids(
        await download_run_artifacts(repo, run.id, installation_id=installation_id)
    )
    if not failed_test_ids:
        return []

    framework = await detect_framework(repo, run.head_sha, installation_id=installation_id)
    await dispatch_workflow(
        repo,
        RERUN_WORKFLOW_FILE,
        ref=default_branch,
        inputs={
            "sha": run.head_sha,
            "test_ids": json.dumps(failed_test_ids),
            "framework": framework,
            "attempts": str(get_settings().rerun_attempts),
            "original_run_id": str(run.id),
            "purpose": "detect",
        },
        installation_id=installation_id,
    )
    return failed_test_ids
