import json

import pytest
from fastapi.testclient import TestClient

from api.deps import get_github_app, get_graph
from core.config import Settings, get_settings
from graph.nodes import check_flaky
from main import app
from tests.helpers import (
    INSTALLATION_TOKEN,
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
DISPATCH = r"/repos/acme/shop/actions/workflows/flaky-rerun.yml/dispatches"


def post_run_event(client: TestClient, **run_fields) -> dict:
    event_fields = {k: run_fields.pop(k) for k in ("action", "installation") if k in run_fields}
    payload = workflow_run_event(workflow_run(**run_fields), **event_fields)
    response = signed_post(client, GITHUB, payload, event="workflow_run")
    assert response.status_code == 202, response.text
    return response.json()


# --- Signature ------------------------------------------------------------------------


def test_rejects_missing_or_wrong_signature(client: TestClient) -> None:
    payload = workflow_run_event(workflow_run())

    unsigned = client.post(GITHUB, json=payload, headers={"X-GitHub-Event": "workflow_run"})
    forged = signed_post(client, GITHUB, payload, event="workflow_run", signature="sha256=00")

    assert unsigned.status_code == 401
    assert forged.status_code == 401


def test_refuses_everything_without_a_configured_secret(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)

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


# --- Phase A: failed CI run → dispatch the Flaky Rerun ---------------------------------


def test_failed_watched_run_dispatches_the_rerun(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    ack = post_run_event(client, run_id=111, name="CI")

    assert ack == {
        "received": True,
        "action": "rerun_dispatched",
        "reason": None,
        "thread_id": "111",
    }
    [dispatch] = fake_github.calls("POST", DISPATCH)
    assert dispatch.headers["Authorization"] == f"Bearer {INSTALLATION_TOKEN}"
    body = json.loads(dispatch.content)
    assert body["ref"] == "main"  # always the default branch, never the PR branch
    assert body["inputs"] == {"original_run_id": "111", "head_sha": "abc123def", "attempts": "10"}
    assert fake_graph.invocations == []  # phase A never runs the graph


def test_duplicate_delivery_dispatches_once(client: TestClient, fake_github: FakeGitHub) -> None:
    first = post_run_event(client, run_id=111)
    second = post_run_event(client, run_id=111)
    retried_by_user = post_run_event(client, run_id=111, run_attempt=2)

    assert first["action"] == "rerun_dispatched"
    assert second["action"] == "ignored"
    assert retried_by_user["action"] == "rerun_dispatched"
    assert len(fake_github.calls("POST", DISPATCH)) == 2


@pytest.mark.parametrize(
    ("run_fields", "reason_fragment"),
    [
        ({"conclusion": "success"}, "not 'failure'"),
        ({"conclusion": "cancelled"}, "not 'failure'"),
        ({"name": "Lint"}, "WATCHED_WORKFLOWS"),
        ({"head_repository": "stranger/shop"}, "fork"),
        ({"installation": False}, "installation"),
        ({"action": "requested"}, "action 'requested'"),
    ],
)
def test_runs_that_should_not_be_rerun_are_ignored(
    client: TestClient, fake_github: FakeGitHub, run_fields: dict, reason_fragment: str
) -> None:
    ack = post_run_event(client, **run_fields)

    assert ack["action"] == "ignored"
    assert reason_fragment in ack["reason"]
    assert fake_github.calls("POST", DISPATCH) == []


def test_empty_watch_list_watches_every_workflow(
    client: TestClient, settings: Settings, fake_github: FakeGitHub
) -> None:
    settings.watched_workflows = []

    assert post_run_event(client, name="Lint")["action"] == "rerun_dispatched"


def test_rejected_dispatch_is_a_502_and_can_be_redelivered(
    client: TestClient, fake_github: FakeGitHub
) -> None:
    fake_github.dispatch_status = 404  # e.g. flaky-rerun.yml missing from the default branch
    payload = workflow_run_event(workflow_run(run_id=111))

    rejected = signed_post(client, GITHUB, payload, event="workflow_run")
    fake_github.dispatch_status = 204
    redelivered = signed_post(client, GITHUB, payload, event="workflow_run")

    assert rejected.status_code == 502
    assert "404" in rejected.json()["detail"]
    assert redelivered.json()["action"] == "rerun_dispatched"


def test_dispatch_needs_the_github_app(client: TestClient) -> None:
    app.dependency_overrides[get_github_app] = lambda: None

    response = signed_post(client, GITHUB, workflow_run_event(workflow_run()), event="workflow_run")

    assert response.status_code == 503


# --- Phase B: Flaky Rerun completed → collect JUnit, run the graph ---------------------


def seed_rerun_evidence(fake_github: FakeGitHub) -> None:
    fake_github.runs[111] = workflow_run(run_id=111)
    # Original CI run uploaded its report: attempt 0.
    fake_github.add_artifact(111, "junit-results", make_zip({"report.xml": junit("pytest.xml")}))
    for attempt, fixture in [
        (1, "pytest_passing.xml"),
        (2, "pytest.xml"),
        (3, "pytest_passing.xml"),
    ]:
        fake_github.add_artifact(
            222, f"junit-attempt-{attempt}", make_zip({"r.xml": junit(fixture)})
        )


def rerun_completed(**overrides) -> dict:
    fields = {
        "run_id": 222,
        "name": "Flaky Rerun",
        "display_title": "Flaky Rerun #111",
        "conclusion": "failure",
    } | overrides
    return fields


def test_completed_rerun_runs_the_graph_on_its_junit(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    seed_rerun_evidence(fake_github)

    ack = post_run_event(client, **rerun_completed())

    assert ack["action"] == "analysis_scheduled"
    assert ack["thread_id"] == "111"
    assert fake_github.calls("POST", DISPATCH) == []  # the rerun's own failure isn't re-rerun
    [(state, config)] = fake_graph.invocations
    assert config == {"configurable": {"thread_id": "111"}}

    payload = state["github_payload"]
    assert payload["repository"] == "acme/shop"  # the string clone_repo needs
    assert payload["branch"] == "feature/inventory"
    assert payload["run_id"] == "111"
    assert payload["rerun_run_id"] == "222"
    assert payload["pull_requests"] == [7]
    assert payload["installation_id"] == 99
    assert INSTALLATION_TOKEN not in json.dumps(state)  # state is checkpointed + displayed

    [result] = state["rerun_results"]
    assert result["test_id"] == "tests.test_inventory::test_concurrent_reserve"
    assert (result["attempts"], result["passed"], result["failed"]) == (4, 2, 2)
    assert "FAILED tests.test_inventory::test_concurrent_reserve" in state["logs"]
    assert state["callback_url"] == "https://github.com/acme/shop/actions/runs/111"
    assert check_flaky(state) == {"is_flaky": True}


def test_rerun_without_original_run_id_is_ignored(
    client: TestClient, fake_graph: FakeGraph
) -> None:
    ack = post_run_event(client, **rerun_completed(display_title="Flaky Rerun"))

    assert ack["action"] == "ignored"
    assert fake_graph.invocations == []


def test_already_analysed_run_is_not_rerun_through_the_graph(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    seed_rerun_evidence(fake_github)
    fake_graph.threads["111"] = {"is_flaky": True}

    ack = post_run_event(client, **rerun_completed())

    assert ack == {
        "received": True,
        "action": "ignored",
        "reason": "this run was already analyzed",
        "thread_id": "111",
    }
    assert fake_graph.invocations == []


def test_rerun_without_junit_artifacts_does_not_run_the_graph(
    client: TestClient, fake_github: FakeGitHub, fake_graph: FakeGraph
) -> None:
    fake_github.runs[111] = workflow_run(run_id=111)

    ack = post_run_event(client, **rerun_completed())

    assert ack["action"] == "analysis_scheduled"
    assert fake_graph.invocations == []


# --- Manual JUnit ingest ----------------------------------------------------------------


def junit_ingest_payload(**overrides) -> dict:
    return {
        "repository": "octocat/Hello-World",
        "run_id": "local-1",
        "branch": "main",
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
