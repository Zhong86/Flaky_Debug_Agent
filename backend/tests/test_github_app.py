import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from schemas.github import WorkflowRun
from services import github_artifacts
from services.github_app import GitHubApp
from tests.helpers import INSTALLATION_TOKEN, FakeGitHub, junit, make_zip, workflow_run

REPO = "acme/shop"


def test_app_jwt_is_rs256_signed_with_github_claims(
    github_app: GitHubApp, private_key_pem: str
) -> None:
    now = time.time()
    public_key = load_pem_private_key(private_key_pem.encode(), None).public_key()

    claims = jwt.decode(github_app.app_jwt(now), public_key, algorithms=["RS256"])

    assert claims["iss"] == "12345"
    assert claims["iat"] == int(now) - 60  # backdated for clock drift
    assert claims["exp"] - claims["iat"] == 600  # GitHub's 10 minute maximum


async def test_installation_token_is_cached(github_app: GitHubApp, fake_github: FakeGitHub) -> None:
    assert await github_app.installation_token(99) == INSTALLATION_TOKEN
    assert await github_app.installation_token(99) == INSTALLATION_TOKEN

    [token_request] = fake_github.calls("POST", r"/app/installations/99/access_tokens")
    assert token_request.headers["Authorization"].startswith("Bearer ey")  # the app JWT


async def test_installation_token_near_expiry_is_refreshed(
    github_app: GitHubApp, fake_github: FakeGitHub
) -> None:
    fake_github.token_expires_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)
    )

    await github_app.installation_token(99)
    await github_app.installation_token(99)

    assert len(fake_github.calls("POST", r"/app/installations/99/access_tokens")) == 2


async def test_dispatch_rerun_sends_the_contract_inputs(
    github_app: GitHubApp, fake_github: FakeGitHub
) -> None:
    run = WorkflowRun.model_validate(workflow_run(run_id=111))

    async with await github_app.installation_client(99) as client:
        await github_artifacts.dispatch_rerun(
            client,
            repository=REPO,
            ref="main",
            workflow_file="flaky-rerun.yml",
            run=run,
            attempts=10,
        )

    [dispatch] = fake_github.calls(
        "POST", rf"/repos/{REPO}/actions/workflows/flaky-rerun.yml/dispatches"
    )
    assert dispatch.headers["Authorization"] == f"Bearer {INSTALLATION_TOKEN}"
    assert json.loads(dispatch.content) == {
        "ref": "main",
        "inputs": {"original_run_id": "111", "head_sha": "abc123def", "attempts": "10"},
    }


async def test_download_maps_attempt_artifacts_and_keeps_only_xml(
    github_app: GitHubApp, fake_github: FakeGitHub
) -> None:
    fake_github.add_artifact(222, "junit-attempt-1", make_zip({"report.xml": junit("pytest.xml")}))
    fake_github.add_artifact(
        222,
        "junit-attempt-2",
        make_zip({"a/TEST-1.xml": junit("surefire.xml"), "b/TEST-2.xml": junit("jest.xml")}),
    )
    fake_github.add_artifact(222, "junit-attempt-3", make_zip({"notes.txt": b"no xml here"}))
    fake_github.add_artifact(222, "junit-attempt-4", make_zip({"r.xml": b"<x/>"}), expired=True)
    fake_github.add_artifact(222, "coverage-report", make_zip({"coverage.xml": b"<coverage/>"}))
    fake_github.add_artifact(222, "junit-summary", make_zip({"r.xml": b"<x/>"}))  # no attempt

    async with await github_app.installation_client(99) as client:
        reports = await github_artifacts.download_rerun_artifacts(
            client, REPO, 222, prefix="junit", max_bytes=1_000_000
        )

    assert {attempt: len(files) for attempt, files in reports.items()} == {1: 1, 2: 2}
    assert reports[1] == [junit("pytest.xml")]


async def test_download_can_file_every_artifact_under_one_attempt(
    github_app: GitHubApp, fake_github: FakeGitHub
) -> None:
    fake_github.add_artifact(111, "junit-results", make_zip({"r.xml": junit("pytest.xml")}))
    fake_github.add_artifact(111, "junit-attempt-7", make_zip({"r.xml": junit("jest.xml")}))

    async with await github_app.installation_client(99) as client:
        reports = await github_artifacts.download_rerun_artifacts(
            client, REPO, 111, prefix="junit", max_bytes=1_000_000, attempt_for_all=0
        )

    assert list(reports) == [0]
    assert len(reports[0]) == 2


async def test_artifact_download_does_not_leak_the_token_to_blob_storage(
    github_app: GitHubApp, fake_github: FakeGitHub
) -> None:
    fake_github.add_artifact(222, "junit-attempt-1", make_zip({"r.xml": junit("pytest.xml")}))

    async with await github_app.installation_client(99) as client:
        await github_artifacts.download_rerun_artifacts(
            client, REPO, 222, prefix="junit", max_bytes=1_000_000
        )

    [blob_request] = [r for r in fake_github.requests if r.url.host == "blob.example"]
    assert "Authorization" not in blob_request.headers


async def test_download_enforces_the_size_budget(
    github_app: GitHubApp, fake_github: FakeGitHub
) -> None:
    fake_github.add_artifact(
        222, "junit-attempt-1", make_zip({"r.xml": b"<x>" + b"a" * 5000 + b"</x>"})
    )

    async with await github_app.installation_client(99) as client:
        with pytest.raises(github_artifacts.ArtifactsTooLarge):
            await github_artifacts.download_rerun_artifacts(
                client, REPO, 222, prefix="junit", max_bytes=1_000
            )
