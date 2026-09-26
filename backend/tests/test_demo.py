"""services/github_jobs.py and api/routes/demo.py against a fake GitHub."""

import logging

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from services import github_jobs
from services.github_app import GitHubApp
from tests.helpers import INSTALLATION_TOKEN, FakeGitHub, workflow_run

REPO = "acme/ticket-booking"
DEMO = "/api/demo"


@pytest.fixture(autouse=True)
def demo_repo(settings: Settings) -> None:
    settings.demo_repo = REPO


# --- github_jobs ---------------------------------------------------------------------


async def test_list_run_jobs_returns_the_jobs(fake_github: FakeGitHub) -> None:
    fake_github.set_jobs(300, [{"id": 1, "name": "test"}, {"id": 2, "name": "deploy"}])

    jobs = await github_jobs.list_run_jobs(REPO, 300)

    assert [j["name"] for j in jobs] == ["test", "deploy"]


async def test_list_run_jobs_is_empty_when_none_were_set(fake_github: FakeGitHub) -> None:
    assert await github_jobs.list_run_jobs(REPO, 999) == []


async def test_get_job_logs_returns_the_text(fake_github: FakeGitHub) -> None:
    fake_github.set_job_logs(11, "Running tests...\nDone.")

    assert await github_jobs.get_job_logs(REPO, 11) == "Running tests...\nDone."


async def test_get_job_logs_is_empty_before_the_job_starts(fake_github: FakeGitHub) -> None:
    # GitHub 404s a job's logs until a runner has picked it up.
    assert await github_jobs.get_job_logs(REPO, 404) == ""


# --- POST /demo/dispatch --------------------------------------------------------------


def test_config_reports_the_demo_repo_and_its_urls(client: TestClient) -> None:
    response = client.get(f"{DEMO}/config")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["repo"] == REPO
    assert body["repo_url"] == f"https://github.com/{REPO}"
    assert body["actions_url"] == f"https://github.com/{REPO}/actions"


def test_config_is_200_with_null_urls_when_no_demo_repo(client: TestClient, settings: Settings) -> None:
    # Deliberately not 503 like the rest: the dashboard reads `configured` to decide
    # whether to render the repo link, so it must be able to ask without an error.
    settings.demo_repo = ""

    response = client.get(f"{DEMO}/config")

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert response.json()["actions_url"] is None


def test_dispatch_without_a_configured_demo_repo_is_503(client: TestClient, settings: Settings) -> None:
    settings.demo_repo = ""

    response = client.post(f"{DEMO}/dispatch")

    assert response.status_code == 503


def test_dispatch_finds_and_returns_the_new_run(client: TestClient, fake_github: FakeGitHub) -> None:
    fake_github.workflow_runs = [workflow_run(run_id=500, name="Deploy")]
    fake_github.runs[500] = workflow_run(run_id=500, name="Deploy", status="queued", conclusion=None)

    response = client.post(f"{DEMO}/dispatch")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "run_id": 500,
        "html_url": "https://github.com/acme/shop/actions/runs/500",
        "status": "queued",
    }
    [dispatch] = fake_github.dispatches()
    assert dispatch == {"ref": "main", "inputs": {}}
    dispatched = fake_github.calls("POST", r"/repos/acme/ticket-booking/actions/workflows/deploy\.yml/dispatches")
    assert len(dispatched) == 1


def test_dispatch_authenticates_as_the_app_when_one_is_installed(
    client: TestClient, fake_github: FakeGitHub, github_app: GitHubApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nothing hands the demo an installation_id (no webhook), so it has to resolve one from
    # the repo — without that it silently falls back to the PAT, which 403s on dispatch.
    # Both: demo resolves the installation id, github_client mints the token from it.
    monkeypatch.setattr("api.routes.demo.get_github_app", lambda: github_app)
    monkeypatch.setattr("services.github_client.get_github_app", lambda: github_app)
    fake_github.installations[REPO] = 4242
    fake_github.workflow_runs = [workflow_run(run_id=500, name="Deploy")]
    fake_github.runs[500] = workflow_run(run_id=500, name="Deploy", status="queued", conclusion=None)

    response = client.post(f"{DEMO}/dispatch")

    assert response.status_code == 200, response.text
    [dispatch] = fake_github.calls("POST", r"/repos/acme/ticket-booking/actions/workflows/deploy\.yml/dispatches")
    assert dispatch.headers["Authorization"] == f"Bearer {INSTALLATION_TOKEN}"
    assert fake_github.calls("POST", r"/app/installations/4242/access_tokens")


def test_dispatch_is_503_when_the_app_is_not_installed_on_the_demo_repo(
    client: TestClient, fake_github: FakeGitHub, github_app: GitHubApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both: demo resolves the installation id, github_client mints the token from it.
    monkeypatch.setattr("api.routes.demo.get_github_app", lambda: github_app)
    monkeypatch.setattr("services.github_client.get_github_app", lambda: github_app)
    fake_github.installations.clear()

    response = client.post(f"{DEMO}/dispatch")

    assert response.status_code == 503
    assert "not installed" in response.json()["detail"]
    assert not fake_github.dispatches()


# --- GET /demo/runs/{run_id} -----------------------------------------------------------


def test_get_run_shapes_jobs_and_steps(client: TestClient, fake_github: FakeGitHub) -> None:
    fake_github.runs[500] = workflow_run(run_id=500, name="Deploy", status="in_progress", conclusion=None)
    fake_github.set_jobs(
        500,
        [
            {
                "id": 1,
                "name": "test",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-01-01T00:00:00Z",
                "completed_at": "2026-01-01T00:01:00Z",
                "steps": [{"name": "Checkout", "number": 1, "status": "completed", "conclusion": "success"}],
            },
            {
                "id": 2,
                "name": "deploy",
                "status": "in_progress",
                "conclusion": None,
                "started_at": "2026-01-01T00:01:00Z",
                "completed_at": None,
                "steps": [],
            },
        ],
    )

    response = client.get(f"{DEMO}/runs/500")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert [job["name"] for job in body["jobs"]] == ["test", "deploy"]
    assert body["jobs"][0]["steps"] == [
        {"name": "Checkout", "number": 1, "status": "completed", "conclusion": "success"}
    ]
    assert body["jobs"][1]["steps"] == []


# --- GET /demo/jobs/{job_id}/logs -------------------------------------------------------


def test_get_job_logs_route_when_available(client: TestClient, fake_github: FakeGitHub) -> None:
    fake_github.set_job_logs(1, "some log text")

    response = client.get(f"{DEMO}/jobs/1/logs")

    assert response.json() == {"available": True, "logs": "some log text"}


def test_get_job_logs_route_before_the_job_starts(client: TestClient) -> None:
    response = client.get(f"{DEMO}/jobs/999/logs")

    assert response.json() == {"available": False, "logs": ""}


# --- GET /demo/backend-logs -------------------------------------------------------------


def test_backend_logs_captures_this_apps_own_logging(client: TestClient) -> None:
    logging.getLogger("services.whatever").info("hello from a test")

    response = client.get(f"{DEMO}/backend-logs")

    assert response.status_code == 200
    messages = [entry["message"] for entry in response.json()["entries"]]
    assert "hello from a test" in messages
