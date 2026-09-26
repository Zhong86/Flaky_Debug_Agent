"""graph/nodes.py's git plumbing (clone_repo, code_fix) and where the graph goes after a clone."""

import base64
import subprocess
from pathlib import Path

import pytest

from graph import nodes
from graph.graph import _route_cloned
from tests.helpers import GITHUB_TOKEN

# What git prints when GitHub rejects the credentials and there's no terminal to prompt on.
AUTH_REJECTED = "fatal: could not read Username for 'https://github.com': No such device or address"


class FakeGit:
    """Stands in for subprocess.run: records every git command, failing the given subcommand."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.fail_on: str | None = None

    def __call__(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.commands.append(cmd)
        if self.fail_on in cmd:
            raise subprocess.CalledProcessError(128, cmd, stderr=f"{AUTH_REJECTED}\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")

    def command(self, subcommand: str) -> list[str]:
        [cmd] = [c for c in self.commands if subcommand in c]
        return cmd


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeGit:
    fake = FakeGit()
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setattr(nodes.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    return fake


def state(**fields) -> dict:
    return {
        "github_payload": {"repository": "acme/shop", "branch": "main"},
        "rerun_results": [],
        "debug_findings": "Race between check and decrement in reserve()",
        "installation_id": None,  # no App installation → the GITHUB_TOKEN PAT
    } | fields


def assert_basic_auth(cmd: list[str]) -> None:
    """GitHub's git endpoint rejects bearer tokens: it wants Basic x-access-token:<token>."""
    [header] = [arg.split("=", 1)[1] for arg in cmd if arg.startswith("http.extraheader=")]
    scheme, credentials = header.removeprefix("AUTHORIZATION: ").split(" ", 1)
    assert scheme == "basic"
    assert base64.b64decode(credentials).decode() == f"x-access-token:{GITHUB_TOKEN}"
    assert not any(GITHUB_TOKEN in arg for arg in cmd)  # never in plain text, URL included


async def test_clone_authenticates_with_basic_x_access_token(
    fake_git: FakeGit, tmp_path: Path
) -> None:
    result = await nodes.clone_repo(state())

    clone = fake_git.command("clone")
    assert_basic_auth(clone)
    assert clone[-2:] == ["https://github.com/acme/shop.git", str(tmp_path)]
    assert result == {"repo_path": str(tmp_path)}


async def test_failed_clone_is_reported_and_ends_the_run(fake_git: FakeGit) -> None:
    fake_git.fail_on = "clone"

    result = await nodes.clone_repo(state())

    assert result["repo_path"] == ""
    assert result["debug_findings"] == f"[clone_repo error] {AUTH_REJECTED}"
    # Bob must not investigate (or "fix") whatever directory the backend happens to run in.
    assert _route_cloned(state() | result) == "output"


@pytest.mark.parametrize(
    ("repo_path", "next_node"), [("/tmp/flaky-debug-x", "debug_agent"), ("", "output")]
)
def test_route_after_clone(repo_path: str, next_node: str) -> None:
    assert _route_cloned(state(repo_path=repo_path)) == next_node


async def test_fix_branch_is_pushed_with_basic_auth(
    fake_git: FakeGit, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(nodes, "fixer_agent", lambda _state: {"fix_applied": True})

    result = await nodes.code_fix(state(repo_path="/tmp/flaky-debug-x"))

    assert_basic_auth(fake_git.command("push"))
    assert result["fix_applied"] is True
    assert result["fix_branch"].startswith("flaky-fix/")
    assert result["fix_sha"] == "abc123"
