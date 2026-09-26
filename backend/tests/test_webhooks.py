import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from api.deps import get_graph
from core.config import Settings
from graph.nodes import check_flaky
from main import app
from services.github_dispatch import rerun_title
from tests.helpers import (
    GITHUB_TOKEN,
    FakeGitHub,
    FakeGraph,
    junit,
    make_zip,
    signed_post,
    workflow_run,
    workflow_run_event,
)

GITHUB = "/api/webhooks/github"
JUNIT = "/api/webhooks/junit"
FLAKY_TEST = "tests/test_inventory.py::test_concurrent_reserve"


def post_run_event(client: TestClient, action: str = "completed", **run_fields) -> dict:
    payload = workflow_run_event(workflow_run(**run_fields), action=action)
    response = signed_post(client, GITHUB, payload, event="workflow_run")
    assert response.status_code == 202, response.text
    return response.json()


def seed_failed_ci_run(fake_github: FakeGitHub, run_id: int = 111) -> None:
    """The original CI run uploaded a JUnit report with one failing test."""
    fake_github.runs[run_id] = workflow_run(run_id=run_id)
    fake_github.add_artifact(run_id, "junit-results", make_zip({"report.xml": junit("pytest.xml")}))


# --- Signature ------------------------------------------------------------------------


def test_rejects_missing_or_wrong_signature(client: TestClient, fake_github: FakeGitHub) -> None:
    payload = workflow_run_event(workflow_run())

    unsigned = client.post(GITHUB, json=payload, headers={"X-GitHub-Event": "workflow_run"})
    forged = signed_post(client, GITHUB, payload, event="workflow_run", signature="sha256=00")

    assert unsigned.status_code == forged.status_code == 401
    assert fake_github.requests == []  # nothing reached GitHub


@pytest.mark.parametrize("secret", [None, ""])
def test_refuses_everything_without_a_configured_secret(
    client: TestClient, settings: Settings, secret: str | None
) -> None:
    settings.github_webhook_secret = None if secret is None else SecretStr(secret)

    response = signed_post(client, GITHUB, {"zen": "hi"}, event="ping")

    assert response.status_code == 503


def test_ping_and_other_events_are_acknowledged_and_ignored(client: TestClient) -> None:
    ping = signed_post(client, GITHUB, {"zen": "Keep it logically awesome."}, event="ping")
    push = signed_post(client, GITHUB, {"ref": "refs/heads/main"}, event="push")

    assert ping.status_code == push.status_code == 202
    assert ping.json()["action"] == push.json()["action"] == "ignored"


def test_malformed_workflow_run_payload_is_a_422(client: TestClient) -> None:
    response = signed_post(client, GITHUB, {"action": "completed"}, event="workflow_run")

    assert response.status_code == 422


# --- Phase A: failed CI run → dispatch the detect rerun --------------------------------


def test_failed_watched_run_dispatches_a_detect_rerun(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    seed_failed_ci_run(fake_github)

    ack = post_run_event(client, run_id=111, name="CI")

    assert ack == {
        "received": True,
        "action": "rerun_scheduled",
        "reason": None,
        "thread_id": "111",
    }
    [dispatch] = fake_github.dispatches()
    assert dispatch["ref"] == "main"  # the default branch, never the PR branch
    assert dispatch["inputs"] == {
        "sha": "abc123def",
        "test_ids": json.dumps([FLAKY_TEST]),
        "framework": "pytest",
        "attempts": "5",
        "original_run_id": "111",
        "purpose": "detect",
    }
    assert fake_graph.invocations == []  # phase A never runs the graph


def test_duplicate_delivery_dispatches_once(client: TestClient, fake_github: FakeGitHub) -> None:
    seed_failed_ci_run(fake_github)

    first = post_run_event(client, run_id=111)
    redelivered = post_run_event(client, run_id=111)
    rerun_by_user = post_run_event(client, run_id=111, run_attempt=2)

    assert first["action"] == "rerun_scheduled"
    assert redelivered["action"] == "ignored"
    assert rerun_by_user["action"] == "rerun_scheduled"
    assert len(fake_github.dispatches()) == 2


@pytest.mark.parametrize(
    ("event_fields", "reason_fragment"),
    [
        ({"conclusion": "success"}, "not 'failure'"),
        ({"conclusion": "cancelled"}, "not 'failure'"),
        ({"name": "Lint"}, "WATCHED_WORKFLOWS"),
        ({"head_repository": "stranger/shop"}, "fork"),
        ({"action": "requested"}, "action 'requested'"),
    ],
)
def test_runs_that_should_not_be_rerun_are_ignored(
    client: TestClient, fake_github: FakeGitHub, event_fields: dict, reason_fragment: str
) -> None:
    ack = post_run_event(client, **event_fields)

    assert ack["action"] == "ignored"
    assert reason_fragment in ack["reason"]
    assert fake_github.requests == []


def test_empty_watch_list_watches_every_workflow(
    client: TestClient, settings: Settings, fake_github: FakeGitHub
) -> None:
    settings.watched_workflows = []
    seed_failed_ci_run(fake_github)

    assert post_run_event(client, name="Lint")["action"] == "rerun_scheduled"
    assert len(fake_github.dispatches()) == 1


def test_run_without_failing_junit_dispatches_nothing(
    client: TestClient, fake_github: FakeGitHub
) -> None:
    fake_github.add_artifact(111, "junit-results", make_zip({"r.xml": junit("pytest_passing.xml")}))

    assert post_run_event(client, run_id=111)["action"] == "rerun_scheduled"
    assert fake_github.dispatches() == []


def test_rejected_dispatch_can_be_redelivered(client: TestClient, fake_github: FakeGitHub) -> None:
    seed_failed_ci_run(fake_github)
    fake_github.dispatch_status = 404  # e.g. flaky-rerun.yml missing from the default branch

    first = post_run_event(client, run_id=111)
    fake_github.dispatch_status = 204
    redelivered = post_run_event(client, run_id=111)

    assert first["action"] == redelivered["action"] == "rerun_scheduled"
    assert len(fake_github.dispatches()) == 2  # the failed one released its claim


def test_github_token_is_required(client: TestClient, settings: Settings) -> None:
    settings.github_token = ""

    response = signed_post(client, GITHUB, workflow_run_event(workflow_run()), event="workflow_run")

    assert response.status_code == 503


# --- Phase B: detect rerun completed → collect JUnit, run the graph --------------------


def seed_detect_rerun(fake_github: FakeGitHub) -> None:
    seed_failed_ci_run(fake_github, run_id=111)  # attempt 0
    for attempt, fixture in [
        (1, "pytest_passing.xml"),
        (2, "pytest.xml"),
        (3, "pytest_passing.xml"),
    ]:
        fake_github.add_artifact(
            222, f"rerun-attempt-{attempt}", make_zip({"r.xml": junit(fixture)})
        )


def rerun_completed(title: str = rerun_title("detect", "111", "abc123def"), **fields) -> dict:
    return {
        "run_id": 222,
        "name": "Flaky Rerun",
        "display_title": title,
        "conclusion": "failure",
    } | fields


def test_completed_detect_rerun_runs_the_graph(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    seed_detect_rerun(fake_github)

    ack = post_run_event(client, **rerun_completed())

    assert ack["action"] == "analysis_scheduled"
    assert ack["thread_id"] == "111"
    assert fake_github.dispatches() == []  # the rerun's own "failure" isn't re-rerun
    [(state, config)] = fake_graph.invocations
    assert config == {"configurable": {"thread_id": "111"}}

    payload = state["github_payload"]
    assert payload["repository"] == "acme/shop"  # the string clone_repo needs
    assert payload["branch"] == "feature/inventory"
    assert payload["sha"] == "abc123def"  # what retest_flaky falls back to
    assert payload["run_id"] == "111"
    assert payload["rerun_run_id"] == "222"
    assert payload["pull_requests"] == [7]
    assert GITHUB_TOKEN not in json.dumps(state)  # state is checkpointed + displayed

    results = {r["test_id"]: r for r in state["rerun_results"]}
    flaky = results[FLAKY_TEST]
    # attempt 0 (CI) failed, reruns 1 and 3 passed, rerun 2 failed
    assert (flaky["attempts"], flaky["passed"], flaky["failed"]) == (4, 2, 2)
    assert f"FAILED {FLAKY_TEST}" in state["logs"]
    assert state["callback_url"] == "https://github.com/acme/shop/actions/runs/111"
    assert (state["fix_branch"], state["fix_sha"]) == ("", "")
    assert check_flaky(state) == {"is_flaky": True}


def test_ci_failure_that_passes_every_rerun_is_still_flaky(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    seed_failed_ci_run(fake_github, run_id=111)
    for attempt in range(1, 6):
        fake_github.add_artifact(
            222, f"rerun-attempt-{attempt}", make_zip({"r.xml": junit("pytest_passing.xml")})
        )

    post_run_event(client, **rerun_completed())

    [(state, _)] = fake_graph.invocations
    assert check_flaky(state) == {"is_flaky": True}  # 5/6 passed, thanks to attempt 0


def test_retest_runs_are_ignored_so_the_graph_cannot_loop(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    ack = post_run_event(client, **rerun_completed(title=rerun_title("retest", "", "f1x")))

    assert ack["action"] == "ignored"
    assert "retest_flaky" in ack["reason"]
    assert fake_graph.invocations == []
    assert fake_github.requests == []


@pytest.mark.parametrize("title", ["Flaky Rerun", rerun_title("detect", "", "abc123def")])
def test_reruns_without_an_original_run_are_ignored(
    client: TestClient, fake_graph: FakeGraph, title: str
) -> None:
    ack = post_run_event(client, **rerun_completed(title=title))

    assert ack["action"] == "ignored"
    assert fake_graph.invocations == []


def test_already_analyzed_run_is_not_rerun_through_the_graph(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    seed_detect_rerun(fake_github)
    fake_graph.threads["111"] = {"is_flaky": True}

    ack = post_run_event(client, **rerun_completed())

    assert ack == {
        "received": True,
        "action": "ignored",
        "reason": "this run was already analyzed",
        "thread_id": "111",
    }
    assert fake_graph.invocations == []


def test_failed_graph_run_can_be_redelivered(
    client: TestClient,
    fake_github: FakeGitHub,
    fake_graph: FakeGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_detect_rerun(fake_github)
    real_ainvoke = fake_graph.ainvoke

    async def crash(state, config):
        raise RuntimeError("bob exploded")

    monkeypatch.setattr(fake_graph, "ainvoke", crash)
    post_run_event(client, **rerun_completed())
    monkeypatch.setattr(fake_graph, "ainvoke", real_ainvoke)
    redelivered = post_run_event(client, **rerun_completed())

    assert redelivered["action"] == "analysis_scheduled"
    assert len(fake_graph.invocations) == 1


def test_rerun_without_junit_artifacts_does_not_run_the_graph(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    fake_github.runs[111] = workflow_run(run_id=111)

    assert post_run_event(client, **rerun_completed())["action"] == "analysis_scheduled"
    assert fake_graph.invocations == []


# --- Manual JUnit ingest ----------------------------------------------------------------


def junit_ingest_payload(**overrides) -> dict:
    return {
        "repository": "octocat/Hello-World",
        "run_id": "local-1",
        "branch": "master",
        "sha": "7fd1a60",
        "reports": {
            "0": [junit("pytest.xml").decode()],
            "1": [junit("pytest_passing.xml").decode()],
        },
    } | overrides


def test_junit_ingest_runs_the_graph(client: TestClient, fake_graph: FakeGraph) -> None:
    response = signed_post(client, JUNIT, junit_ingest_payload())

    assert response.status_code == 202
    assert response.json()["thread_id"] == "local-1"
    [(state, config)] = fake_graph.invocations
    assert config == {"configurable": {"thread_id": "local-1"}}
    assert state["github_payload"]["repository"] == "octocat/Hello-World"
    assert state["github_payload"]["sha"] == "7fd1a60"
    assert state["github_payload"]["source"] == "junit-ingest"
    assert check_flaky(state) == {"is_flaky": True}


@pytest.mark.parametrize(
    "overrides",
    [{"reports": {}}, {"repository": "not a repo"}, {"run_id": ""}],
)
def test_junit_ingest_validates_after_the_signature(client: TestClient, overrides: dict) -> None:
    response = signed_post(client, JUNIT, junit_ingest_payload(**overrides))

    assert response.status_code == 422


def test_junit_ingest_requires_a_signature(client: TestClient) -> None:
    response = client.post(JUNIT, json=junit_ingest_payload())

    assert response.status_code == 401


def test_junit_ingest_needs_the_graph(client: TestClient) -> None:
    app.dependency_overrides[get_graph] = lambda: None

    response = signed_post(client, JUNIT, junit_ingest_payload())

    assert response.status_code == 503
