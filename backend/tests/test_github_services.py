"""services/github_client.py, github_artifacts.py and github_dispatch.py against a fake GitHub."""

import json
import re
from pathlib import Path

import pytest
import yaml

from core.config import Settings
from schemas.github import WorkflowRun
from services import github_artifacts, github_dispatch
from services.github_app import GitHubApp
from services.github_client import github_client
from tests.helpers import (
    GITHUB_TOKEN,
    INSTALLATION_TOKEN,
    FakeGitHub,
    junit,
    make_zip,
    workflow_run,
)

REPO = "acme/shop"
POLLED = "tests/test_inventory.py::test_concurrent_reserve"
TEMPLATE = Path(__file__).parents[1] / "templates" / "flaky-rerun.yml"


def _render(expression: str, values: dict[str, str]) -> str:
    """Substitute `${{ inputs.x }}` / `${{ matrix.x }}` the way Actions would."""
    return re.sub(r"\$\{\{\s*\w+\.(\w+)\s*\}\}", lambda m: values[m.group(1)], expression)


# --- flaky-rerun.yml contract ---------------------------------------------------------


def test_template_run_name_is_what_the_backend_parses() -> None:
    workflow = yaml.safe_load(TEMPLATE.read_text())
    inputs = {"purpose": "retest", "original_run_id": "", "sha": "f1x"}

    title = _render(workflow["run-name"], inputs)

    assert workflow["name"] == github_dispatch.RERUN_WORKFLOW_NAME
    assert title == github_dispatch.rerun_title("retest", "", "f1x")
    # PyYAML (YAML 1.1) reads the bare `on:` key as the boolean True.
    dispatch_inputs = workflow[True]["workflow_dispatch"]["inputs"]
    assert set(dispatch_inputs) >= {"sha", "test_ids", "original_run_id", "purpose", "attempts"}


def test_template_artifacts_are_what_the_backend_downloads() -> None:
    workflow = yaml.safe_load(TEMPLATE.read_text())
    [upload] = [
        s for s in workflow["jobs"]["rerun"]["steps"] if "upload-artifact" in s.get("uses", "")
    ]

    assert _render(upload["with"]["name"], {"attempt": "3"}).startswith(
        github_artifacts.RERUN_ARTIFACT_PREFIX
    )


# --- github_client ------------------------------------------------------------------


async def test_client_sends_the_pat(fake_github: FakeGitHub) -> None:
    async with await github_client() as client:
        await client.get(f"/repos/{REPO}")

    [request] = fake_github.requests
    assert request.headers["Authorization"] == f"Bearer {GITHUB_TOKEN}"
    assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"


async def test_client_without_a_token_sends_no_auth_header(
    settings: Settings, fake_github: FakeGitHub
) -> None:
    settings.github_token = ""

    async with await github_client() as client:
        await client.get(f"/repos/{REPO}")

    assert "Authorization" not in fake_github.requests[0].headers


async def test_client_with_an_installation_id_prefers_the_app_token(
    fake_github: FakeGitHub, github_app: GitHubApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("services.github_client.get_github_app", lambda: github_app)

    async with await github_client(installation_id=99) as client:
        await client.get(f"/repos/{REPO}")

    [request] = fake_github.calls("GET", rf"/repos/{REPO}")
    assert request.headers["Authorization"] == f"Bearer {INSTALLATION_TOKEN}"


async def test_client_without_installation_id_ignores_a_configured_app(
    fake_github: FakeGitHub, github_app: GitHubApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("services.github_client.get_github_app", lambda: github_app)

    async with await github_client() as client:  # no installation_id: e.g. JUnit ingest
        await client.get(f"/repos/{REPO}")

    [request] = fake_github.requests
    assert request.headers["Authorization"] == f"Bearer {GITHUB_TOKEN}"


# --- github_artifacts ---------------------------------------------------------------


async def test_rerun_artifacts_are_grouped_by_attempt_and_filtered(fake_github: FakeGitHub) -> None:
    fake_github.add_artifact(222, "rerun-attempt-1", make_zip({"r.xml": junit("pytest.xml")}))
    fake_github.add_artifact(
        222,
        "rerun-attempt-2",
        make_zip({"a/TEST-1.xml": junit("surefire.xml"), "b/TEST-2.xml": junit("jest.xml")}),
    )
    fake_github.add_artifact(222, "rerun-attempt-3", make_zip({"notes.txt": b"no xml here"}))
    fake_github.add_artifact(222, "rerun-attempt-4", make_zip({"r.xml": b"<x/>"}), expired=True)
    fake_github.add_artifact(222, "coverage-report", make_zip({"coverage.xml": b"<coverage/>"}))

    reports = await github_artifacts.download_rerun_artifacts(REPO, 222)

    assert {attempt: len(files) for attempt, files in reports.items()} == {1: 1, 2: 2}
    assert reports[1] == [junit("pytest.xml")]
    downloaded = fake_github.calls("GET", r"/repos/acme/shop/actions/artifacts/\d+/zip")
    assert len(downloaded) == 3  # expired and non-rerun artifacts are never fetched


async def test_a_ci_runs_artifacts_count_as_attempt_zero(fake_github: FakeGitHub) -> None:
    fake_github.add_artifact(111, "junit-results", make_zip({"r.xml": junit("pytest.xml")}))
    fake_github.add_artifact(111, "test-output", make_zip({"TEST-x.xml": junit("jest.xml")}))

    reports = await github_artifacts.download_run_artifacts(REPO, 111)

    assert list(reports) == [0]
    assert len(reports[0]) == 2


async def test_size_budget_skips_oversized_artifacts_and_files(
    settings: Settings, fake_github: FakeGitHub
) -> None:
    settings.max_artifact_bytes = 2_000
    big_xml = b"<testsuite>" + b"a" * 5_000 + b"</testsuite>"  # compresses small, unzips big
    fake_github.add_artifact(222, "rerun-attempt-1", make_zip({"big.xml": big_xml}))
    fake_github.add_artifact(222, "rerun-attempt-2", b"x" * 3_000)  # zip itself over budget
    fake_github.add_artifact(222, "rerun-attempt-3", make_zip({"r.xml": junit("jest.xml")}))

    reports = await github_artifacts.download_rerun_artifacts(REPO, 222)

    assert list(reports) == [3]


async def test_artifact_download_does_not_leak_the_token_to_blob_storage(
    fake_github: FakeGitHub,
) -> None:
    fake_github.add_artifact(222, "rerun-attempt-1", make_zip({"r.xml": junit("pytest.xml")}))

    await github_artifacts.download_rerun_artifacts(REPO, 222)

    [blob_request] = [r for r in fake_github.requests if r.url.host == "blob.example"]
    assert "Authorization" not in blob_request.headers


# --- run titles ---------------------------------------------------------------------


def test_rerun_title_round_trips() -> None:
    title = github_dispatch.rerun_title("detect", "111", "abc123def")

    assert title == "Flaky Rerun (detect) #111 @ abc123def"
    assert github_dispatch.parse_rerun_title(title) == ("detect", 111, "abc123def")
    assert github_dispatch.parse_rerun_title(github_dispatch.rerun_title("retest", "", "f1x")) == (
        "retest",
        None,
        "f1x",
    )


@pytest.mark.parametrize(
    "title", ["Flaky Rerun", "Flaky Rerun (deploy) #1 @ abc", "Flaky Rerun (detect) #x @ abc"]
)
def test_titles_outside_the_contract_are_rejected(title: str) -> None:
    assert github_dispatch.parse_rerun_title(title) is None


# --- github_dispatch ----------------------------------------------------------------


async def test_trigger_dispatches_the_failing_tests_on_the_default_branch(
    fake_github: FakeGitHub,
) -> None:
    fake_github.add_artifact(111, "junit-results", make_zip({"r.xml": junit("pytest.xml")}))
    run = WorkflowRun.model_validate(workflow_run(run_id=111))

    test_ids = await github_dispatch.trigger_rerun_workflow(REPO, run, "main")

    assert test_ids == [POLLED]
    [dispatch] = fake_github.dispatches()
    assert dispatch == {
        "ref": "main",
        "inputs": {
            "sha": "abc123def",
            "test_ids": json.dumps([POLLED]),
            "framework": "pytest",
            "attempts": "5",
            "original_run_id": "111",
            "purpose": "detect",
        },
    }


async def test_trigger_does_nothing_without_failing_junit(fake_github: FakeGitHub) -> None:
    fake_github.add_artifact(111, "junit-results", make_zip({"r.xml": junit("pytest_passing.xml")}))
    run = WorkflowRun.model_validate(workflow_run(run_id=111))

    assert await github_dispatch.trigger_rerun_workflow(REPO, run, "main") == []
    assert fake_github.dispatches() == []


# --- framework detection --------------------------------------------------------------


@pytest.mark.parametrize(
    ("marker", "framework"),
    [
        ("go.mod", "go"),
        ("pom.xml", "maven"),
        ("Gemfile", "rspec"),
        ("requirements.txt", "pytest"),
        ("pyproject.toml", "pytest"),
    ],
)
async def test_detect_framework_matches_root_markers(
    fake_github: FakeGitHub, marker: str, framework: str
) -> None:
    fake_github.set_repo_tree("README.md", marker)

    assert await github_dispatch.detect_framework(REPO, "abc123def") == framework


async def test_detect_framework_matches_csproj_anywhere_in_the_root_listing(
    fake_github: FakeGitHub,
) -> None:
    fake_github.set_repo_tree("Shop.Tests.csproj", "Shop.sln")

    assert await github_dispatch.detect_framework(REPO, "abc123def") == "dotnet"


async def test_detect_framework_reads_package_json_for_vitest_vs_jest(
    fake_github: FakeGitHub,
) -> None:
    fake_github.set_repo_tree("package.json")
    fake_github.set_repo_file("package.json", json.dumps({"devDependencies": {"vitest": "^2"}}).encode())

    assert await github_dispatch.detect_framework(REPO, "abc123def") == "vitest"


async def test_detect_framework_defaults_package_json_to_jest(fake_github: FakeGitHub) -> None:
    fake_github.set_repo_tree("package.json")
    fake_github.set_repo_file("package.json", json.dumps({"dependencies": {"jest": "^29"}}).encode())

    assert await github_dispatch.detect_framework(REPO, "abc123def") == "jest"


async def test_detect_framework_falls_back_to_pytest_when_nothing_matches(
    fake_github: FakeGitHub,
) -> None:
    fake_github.set_repo_tree("README.md", "LICENSE")

    assert await github_dispatch.detect_framework(REPO, "abc123def") == "pytest"


async def test_detect_framework_falls_back_to_pytest_when_repo_listing_is_unreadable(
    fake_github: FakeGitHub,
) -> None:
    assert await github_dispatch.detect_framework(REPO, "abc123def") == "pytest"


async def test_trigger_dispatches_the_detected_framework(fake_github: FakeGitHub) -> None:
    fake_github.add_artifact(111, "junit-results", make_zip({"r.xml": junit("pytest.xml")}))
    fake_github.set_repo_tree("pom.xml")
    run = WorkflowRun.model_validate(workflow_run(run_id=111))

    await github_dispatch.trigger_rerun_workflow(REPO, run, "main")

    [dispatch] = fake_github.dispatches()
    assert dispatch["inputs"]["framework"] == "maven"


async def test_find_dispatched_run_matches_the_run_name(fake_github: FakeGitHub) -> None:
    ours = github_dispatch.rerun_title("retest", "", "f1x")
    fake_github.workflow_runs = [
        workflow_run(run_id=300, name="Flaky Rerun", display_title="Flaky Rerun (detect) #9 @ a"),
        workflow_run(run_id=301, name="Flaky Rerun", display_title=ours),
    ]

    matched = await github_dispatch.find_dispatched_run(
        REPO, "flaky-rerun.yml", "2026-01-01T00:00:00Z", display_title=ours
    )
    first_after = await github_dispatch.find_dispatched_run(
        REPO, "flaky-rerun.yml", "2026-01-01T00:00:00Z"
    )

    assert (matched, first_after) == (301, 300)


async def test_rerun_and_wait_retests_and_returns_every_test(fake_github: FakeGitHub) -> None:
    title = github_dispatch.rerun_title("retest", "", "f1x")
    fake_github.workflow_runs = [
        workflow_run(run_id=300, name="Flaky Rerun", display_title="Flaky Rerun (detect) #9 @ a"),
        workflow_run(run_id=301, name="Flaky Rerun", display_title=title),
    ]
    fake_github.runs[301] = workflow_run(run_id=301, name="Flaky Rerun", conclusion="success")
    for attempt in (1, 2):
        fake_github.add_artifact(
            301, f"rerun-attempt-{attempt}", make_zip({"r.xml": junit("pytest_passing.xml")})
        )

    results = await github_dispatch.rerun_and_wait(
        REPO, ref="flaky-fix/1", sha="f1x", test_ids=[POLLED]
    )

    [dispatch] = fake_github.dispatches()
    assert dispatch["ref"] == "flaky-fix/1"
    assert dispatch["inputs"]["purpose"] == "retest"
    # retest_flaky's own check: a fully green retest must come back non-empty.
    assert results and all(r["passed"] == r["attempts"] == 2 for r in results)
    assert POLLED in {r["test_id"] for r in results}
