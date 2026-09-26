"""GitHub Actions calls behind the flaky rerun: dispatch it, then collect its JUnit XML.

Rerun contract (the "Flaky Rerun" workflow in the user's repo, see README):
  - dispatched with inputs `original_run_id`, `head_sha`, `attempts`
  - each matrix attempt uploads an artifact named `<prefix>-attempt-<n>` holding JUnit XML
"""

import io
import logging
import re
import zipfile

import httpx

from schemas.github import WorkflowRun

logger = logging.getLogger(__name__)

_ATTEMPT_SUFFIX = re.compile(r"-attempt-(\d+)$")
_PER_PAGE = 100
_MAX_PAGES = 10


class ArtifactsTooLarge(RuntimeError):
    pass


async def dispatch_rerun(
    client: httpx.AsyncClient,
    *,
    repository: str,
    ref: str,
    workflow_file: str,
    run: WorkflowRun,
    attempts: int,
) -> None:
    response = await client.post(
        f"/repos/{repository}/actions/workflows/{workflow_file}/dispatches",
        json={
            "ref": ref,
            "inputs": {
                "original_run_id": str(run.id),
                "head_sha": run.head_sha,
                "attempts": str(attempts),
            },
        },
    )
    response.raise_for_status()


async def get_run(client: httpx.AsyncClient, repository: str, run_id: int) -> WorkflowRun:
    response = await client.get(f"/repos/{repository}/actions/runs/{run_id}")
    response.raise_for_status()
    return WorkflowRun.model_validate(response.json())


async def _list_artifacts(client: httpx.AsyncClient, repository: str, run_id: int) -> list[dict]:
    artifacts: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        response = await client.get(
            f"/repos/{repository}/actions/runs/{run_id}/artifacts",
            params={"per_page": _PER_PAGE, "page": page},
        )
        response.raise_for_status()
        batch = response.json()["artifacts"]
        artifacts.extend(batch)
        if len(batch) < _PER_PAGE:
            break
    return artifacts


def _attempt_for(name: str, prefix: str, attempt_for_all: int | None) -> int | None:
    if not name.startswith(prefix):
        return None
    if attempt_for_all is not None:
        return attempt_for_all
    match = _ATTEMPT_SUFFIX.search(name)
    return int(match.group(1)) if match else None


def _xml_files(archive: bytes, budget: int) -> tuple[list[bytes], int]:
    """Extract the XML files from an artifact zip, spending at most *budget* bytes."""
    files: list[bytes] = []
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".xml"):
                continue
            if info.file_size > budget:
                raise ArtifactsTooLarge(f"JUnit XML exceeds the {budget} byte budget left")
            budget -= info.file_size
            files.append(zf.read(info))
    return files, budget


async def download_rerun_artifacts(
    client: httpx.AsyncClient,
    repository: str,
    run_id: int,
    *,
    prefix: str,
    max_bytes: int,
    attempt_for_all: int | None = None,
) -> dict[int, list[bytes]]:
    """JUnit XML files of one workflow run, grouped by attempt number.

    Artifacts named `<prefix>...-attempt-<n>` map to attempt n. Pass *attempt_for_all*
    to file every `<prefix>*` artifact under one attempt instead — used for the
    original CI run, whose reports count as attempt 0.
    """
    reports: dict[int, list[bytes]] = {}
    budget = max_bytes
    for artifact in await _list_artifacts(client, repository, run_id):
        attempt = _attempt_for(artifact["name"], prefix, attempt_for_all)
        if attempt is None:
            continue
        if artifact.get("expired"):
            logger.warning("Artifact %s of run %s has expired", artifact["name"], run_id)
            continue
        if artifact.get("size_in_bytes", 0) > budget:
            raise ArtifactsTooLarge(f"Artifact {artifact['name']} exceeds the size budget")

        response = await client.get(f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip")
        response.raise_for_status()
        files, budget = _xml_files(response.content, budget)
        if not files:
            logger.warning("Artifact %s of run %s holds no XML files", artifact["name"], run_id)
            continue
        reports.setdefault(attempt, []).extend(files)
    return reports
