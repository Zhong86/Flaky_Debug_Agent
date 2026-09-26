"""Downloading and parsing JUnit XML artifacts off a GitHub Actions run."""

import io
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import httpx

from core.config import get_settings


def _headers() -> dict:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
    }


def _pytest_node_id(testcase: ET.Element) -> str:
    """Best-effort JUnit classname -> pytest node ID (tests/test_x.py::test_y).

    Breaks for a test class nested inside a module (classname becomes
    "module.ClassName", which this treats as a literal path segment) — fine
    for the common flat-function case; a real implementation needs the
    framework's own name resolution, not string surgery.
    """
    classname = testcase.get("classname", "")
    name = testcase.get("name", "")
    path = classname.replace(".", "/") + ".py"
    return f"{path}::{name}"


async def download_run_artifacts(repo: str, run_id: int) -> list[Path]:
    """Download every artifact attached to a run and return local paths to the XML files inside."""
    dest_dir = Path(tempfile.mkdtemp(prefix="flaky-artifacts-"))
    xml_paths: list[Path] = []

    async with httpx.AsyncClient(
        base_url=get_settings().github_api_base, follow_redirects=True, timeout=30
    ) as client:
        resp = await client.get(f"/repos/{repo}/actions/runs/{run_id}/artifacts", headers=_headers())
        resp.raise_for_status()

        for artifact in resp.json()["artifacts"]:
            zip_resp = await client.get(
                f"/repos/{repo}/actions/artifacts/{artifact['id']}/zip", headers=_headers()
            )
            zip_resp.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
                zf.extractall(dest_dir)
                xml_paths += [dest_dir / name for name in zf.namelist() if name.endswith(".xml")]

    return xml_paths


# Kept as the name webhooks.py already imports — same thing, one rerun's worth of artifacts.
download_rerun_artifacts = download_run_artifacts


def parse_junit_results(xml_paths: list[Path]) -> list[dict]:
    """Aggregate N rerun-attempt XML files into per-test pass/fail tallies.

    [{"test_id": "tests/test_x.py::test_y", "attempts": 5, "passed": 3, "failed": 2}]
    """
    tally: dict[str, dict] = {}
    for path in xml_paths:
        root = ET.parse(path).getroot()
        for testcase in root.iter("testcase"):
            test_id = _pytest_node_id(testcase)
            entry = tally.setdefault(test_id, {"test_id": test_id, "attempts": 0, "passed": 0, "failed": 0})
            entry["attempts"] += 1
            failed = testcase.find("failure") is not None or testcase.find("error") is not None
            entry["failed" if failed else "passed"] += 1
    return list(tally.values())


def parse_failed_test_ids(xml_paths: list[Path]) -> list[str]:
    """Pull just the failing pytest node IDs out of a (usually single) JUnit XML file."""
    failed_ids: list[str] = []
    for path in xml_paths:
        root = ET.parse(path).getroot()
        for testcase in root.iter("testcase"):
            if testcase.find("failure") is not None or testcase.find("error") is not None:
                failed_ids.append(_pytest_node_id(testcase))
    return failed_ids
