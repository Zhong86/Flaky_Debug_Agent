"""Dispatching flaky-rerun.yml ("detect") on a target repo's failing tests.

flaky-rerun.yml's `run-name` (rerun_title) carries the purpose and the original
run id, which is how the webhook recognises a finished detect rerun and knows
which CI run it belongs to.
"""

import base64
import json
import re
from datetime import UTC, datetime
from typing import Literal, NamedTuple

from core.config import get_settings
from schemas.github import WorkflowRun
from services.github_artifacts import download_run_artifacts, parse_failed_test_ids
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

# flaky-rerun.yml still accepts "retest" (kept so existing copies of the template stay
# compatible), but the backend only dispatches "detect" and ignores every other purpose.
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


def is_rerun_run(run: WorkflowRun) -> bool:
    """Whether *run* is a flaky-rerun.yml run.

    Matched on the workflow file, not `name`: GitHub reports the workflow's own name
    ("Flaky Rerun") only on `requested` — from `in_progress` on, `name` is the evaluated
    run-name ("Flaky Rerun (detect) #… @ …"). `path` may carry an "@<ref>" suffix.
    """
    return run.path.partition("@")[0] == f".github/workflows/{RERUN_WORKFLOW_FILE}"


async def dispatch_workflow(
    repo: str, workflow_file: str, ref: str, inputs: dict, installation_id: int | None = None
) -> str:
    """Kick off a workflow_dispatch run. Returns the ISO timestamp it was requested at."""
    dispatched_at = datetime.now(UTC).isoformat()
    async with await github_client(installation_id) as client:
        resp = await client.post(
            f"/repos/{repo}/actions/workflows/{workflow_file}/dispatches",
            json={"ref": ref, "inputs": inputs},
        )
        resp.raise_for_status()
    return dispatched_at


async def get_run(repo: str, run_id: int, installation_id: int | None = None) -> dict:
    async with await github_client(installation_id) as client:
        resp = await client.get(f"/repos/{repo}/actions/runs/{run_id}")
        resp.raise_for_status()
        return resp.json()


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
