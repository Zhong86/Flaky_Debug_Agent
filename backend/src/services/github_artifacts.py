"""Downloading and parsing JUnit XML artifacts off a GitHub Actions run.

Artifacts are read in memory — only their `.xml` members, within MAX_ARTIFACT_BYTES —
so nothing lands on disk and a huge build artifact can't exhaust the server.
Parsing lives in services/junit.py; it's re-exported here under the names the
rest of the backend already imports.
"""

import io
import logging
import re
import zipfile

import httpx

from core.config import get_settings
from services.github_client import github_client
from services.junit import parse_failed_test_ids, parse_junit_results

__all__ = [
    "RERUN_ARTIFACT_PREFIX",
    "download_rerun_artifacts",
    "download_run_artifacts",
    "parse_failed_test_ids",
    "parse_junit_results",
]

logger = logging.getLogger(__name__)

# flaky-rerun.yml uploads one artifact per matrix attempt: rerun-attempt-<n>.
RERUN_ARTIFACT_PREFIX = "rerun-attempt-"
_ATTEMPT_SUFFIX = re.compile(r"-attempt-(\d+)$")
_PER_PAGE = 100
_MAX_PAGES = 10


async def _list_artifacts(client: httpx.AsyncClient, repo: str, run_id: int) -> list[dict]:
    artifacts: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        resp = await client.get(
            f"/repos/{repo}/actions/runs/{run_id}/artifacts",
            params={"per_page": _PER_PAGE, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()["artifacts"]
        artifacts += batch
        if len(batch) < _PER_PAGE:
            break
    return artifacts


def _xml_files(archive: bytes, budget: int) -> tuple[list[bytes], int]:
    """The XML members of an artifact zip that fit in *budget* bytes, and what's left of it."""
    files: list[bytes] = []
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".xml"):
                continue
            if info.file_size > budget:
                logger.warning("Skipping %s: over the JUnit size budget", info.filename)
                continue
            budget -= info.file_size
            files.append(zf.read(info))
    return files, budget


async def download_run_artifacts(
    repo: str, run_id: int, name_prefix: str = "", installation_id: int | None = None
) -> dict[int, list[bytes]]:
    """JUnit XML files attached to a run, grouped by attempt number.

    Artifacts named `...-attempt-<n>` count as attempt n; any other artifact is
    attempt 0 — for a regular CI run, its one real execution. Only artifacts whose
    name starts with *name_prefix* are fetched (all of them by default).
    """
    budget = get_settings().max_artifact_bytes
    reports: dict[int, list[bytes]] = {}

    async with await github_client(installation_id) as client:
        for artifact in await _list_artifacts(client, repo, run_id):
            name = artifact["name"]
            if not name.startswith(name_prefix) or artifact.get("expired"):
                continue
            if artifact.get("size_in_bytes", 0) > budget:
                logger.warning("Skipping artifact %s of run %s: over the size budget", name, run_id)
                continue

            zip_resp = await client.get(f"/repos/{repo}/actions/artifacts/{artifact['id']}/zip")
            zip_resp.raise_for_status()
            files, budget = _xml_files(zip_resp.content, budget)
            if not files:
                continue
            match = _ATTEMPT_SUFFIX.search(name)
            reports.setdefault(int(match.group(1)) if match else 0, []).extend(files)

    return reports


async def download_rerun_artifacts(
    repo: str, run_id: int, installation_id: int | None = None
) -> dict[int, list[bytes]]:
    """One flaky-rerun.yml run's worth of artifacts: `rerun-attempt-<n>` → attempt n."""
    return await download_run_artifacts(
        repo, run_id, name_prefix=RERUN_ARTIFACT_PREFIX, installation_id=installation_id
    )
