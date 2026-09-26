import io
import json
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi.testclient import TestClient

from core.security import sign_github_payload

JUNIT_DIR = Path(__file__).parent / "fixtures" / "junit"
WEBHOOK_SECRET = "test-webhook-secret"
GITHUB_TOKEN = "ghp_test_personal_access_token"
INSTALLATION_TOKEN = "ghs_test_installation_token"


def junit(name: str) -> bytes:
    return (JUNIT_DIR / name).read_bytes()


def make_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buffer.getvalue()


class FakeGitHub:
    """Just enough of the GitHub REST API for the rerun flow, served via MockTransport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.runs: dict[int, dict[str, Any]] = {}
        self.workflow_runs: list[dict[str, Any]] = []  # GET .../workflows/<file>/runs
        self.artifacts: dict[int, list[dict[str, Any]]] = {}
        self.blobs: dict[str, bytes] = {}
        self.dispatch_status = 204
        self.token_expires_at = "2099-01-01T00:00:00Z"
        self._next_artifact_id = 1

    def add_artifact(self, run_id: int, name: str, archive: bytes, expired: bool = False) -> None:
        artifact_id = self._next_artifact_id
        self._next_artifact_id += 1
        self.artifacts.setdefault(run_id, []).append(
            {"id": artifact_id, "name": name, "expired": expired, "size_in_bytes": len(archive)}
        )
        self.blobs[f"/artifacts/{artifact_id}.zip"] = archive

    def calls(self, method: str, path_pattern: str) -> list[httpx.Request]:
        return [
            r
            for r in self.requests
            if r.method == method and re.fullmatch(path_pattern, r.url.path)
        ]

    def dispatches(self) -> list[dict[str, Any]]:
        """Bodies of every workflow_dispatch request, in order."""
        pattern = r"/repos/[^/]+/[^/]+/actions/workflows/[^/]+/dispatches"
        return [json.loads(r.content) for r in self.calls("POST", pattern)]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "blob.example":
            return httpx.Response(200, content=self.blobs[path])
        if re.fullmatch(r"/app/installations/\d+/access_tokens", path):
            token = {"token": INSTALLATION_TOKEN, "expires_at": self.token_expires_at}
            return httpx.Response(201, json=token)
        if re.fullmatch(r"/repos/[^/]+/[^/]+/actions/workflows/[^/]+/dispatches", path):
            return httpx.Response(self.dispatch_status)
        if re.fullmatch(r"/repos/[^/]+/[^/]+/actions/workflows/[^/]+/runs", path):
            return httpx.Response(200, json={"workflow_runs": self.workflow_runs})
        if match := re.fullmatch(r"/repos/[^/]+/[^/]+/actions/runs/(\d+)/artifacts", path):
            artifacts = self.artifacts.get(int(match.group(1)), [])
            return httpx.Response(200, json={"total_count": len(artifacts), "artifacts": artifacts})
        if match := re.fullmatch(r"/repos/[^/]+/[^/]+/actions/runs/(\d+)", path):
            run = self.runs.get(int(match.group(1)))
            return httpx.Response(200, json=run) if run else httpx.Response(404)
        if match := re.fullmatch(r"/repos/[^/]+/[^/]+/actions/artifacts/(\d+)/zip", path):
            location = f"https://blob.example/artifacts/{match.group(1)}.zip"
            return httpx.Response(302, headers={"Location": location})
        return httpx.Response(404, json={"message": "Not Found"})


class FakeGraph:
    """Stands in for the checkpointed LangGraph graph: records every invocation."""

    def __init__(self) -> None:
        self.checkpointer = object()
        self.threads: dict[str, dict[str, Any]] = {}
        self.invocations: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def aget_state(self, config: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(values=self.threads.get(config["configurable"]["thread_id"], {}))

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        self.invocations.append((state, config))
        self.threads[config["configurable"]["thread_id"]] = state
        return state


def signed_post(
    client: TestClient,
    path: str,
    payload: dict[str, Any],
    *,
    event: str | None = None,
    signature: str | None = None,
) -> httpx.Response:
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": signature or sign_github_payload(WEBHOOK_SECRET, body),
    }
    if event:
        headers["X-GitHub-Event"] = event
    return client.post(path, content=body, headers=headers)


def workflow_run(
    *,
    run_id: int = 111,
    name: str = "CI",
    conclusion: str | None = "failure",
    display_title: str = "Fix inventory race",
    head_repository: str = "acme/shop",
    run_attempt: int = 1,
    status: str = "completed",
    created_at: str = "2099-01-01T00:00:00Z",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": name,
        "display_title": display_title,
        "head_branch": "feature/inventory",
        "head_sha": "abc123def",
        "status": status,
        "conclusion": conclusion,
        "run_attempt": run_attempt,
        "created_at": created_at,
        "html_url": f"https://github.com/acme/shop/actions/runs/{run_id}",
        "event": "pull_request",
        "pull_requests": [{"number": 7, "url": "https://api.github.com/repos/acme/shop/pulls/7"}],
        "head_repository": {"full_name": head_repository},
    }


def workflow_run_event(run: dict[str, Any], *, action: str = "completed") -> dict[str, Any]:
    return {
        "action": action,
        "workflow_run": run,
        "repository": {"full_name": "acme/shop", "default_branch": "main", "private": True},
        "sender": {"login": "octocat"},
    }
