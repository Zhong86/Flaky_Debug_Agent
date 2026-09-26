import asyncio
import base64
import subprocess
import tempfile

from core.config import get_settings
from graph.agents import documenter_agent, investigator_agents
from graph.state import GraphState
from services.github_app import get_github_app


async def _installation_bearer(state: GraphState) -> str | None:
    """A fresh installation token if the App is installed there, else the GITHUB_TOKEN PAT."""
    installation_id = state.get("installation_id")
    if installation_id is not None and (app := get_github_app()) is not None:
        return await app.installation_token(installation_id)
    return get_settings().github_token or None


def _git_auth(token: str) -> dict[str, str]:
    """git config that authenticates HTTPS git operations against GitHub with *token*.

    GitHub's git endpoint takes Basic auth with username `x-access-token` (installation
    tokens and PATs alike); a bearer header is rejected with 401, which git reports as
    "could not read Username". A header rather than the URL keeps the token out of
    .git/config and git's error messages.
    """
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {"http.extraheader": f"AUTHORIZATION: basic {basic}"}


def check_flaky(state: GraphState) -> dict:
    results = state["rerun_results"]
    # flaky = failed at least once AND passed at least once across identical reruns
    is_flaky = any(0 < r["passed"] < r["attempts"] for r in results)
    return {"is_flaky": is_flaky}


async def clone_repo(state: GraphState) -> dict:
    print("[clone_repo] Cloning repository for debug agent...")
    repository = state["github_payload"].get("repository")
    branch = state["github_payload"].get("branch")

    dest = tempfile.mkdtemp(prefix="flaky-debug-")
    repo_url = f"https://github.com/{repository}.git"

    cmd = ["git"]
    if token := await _installation_bearer(state):
        for key, value in _git_auth(token).items():
            cmd += ["-c", f"{key}={value}"]
    cmd += ["clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, dest]

    try:
        await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True, text=True)
        print(f"[clone_repo] Cloned {repository} -> {dest}")
        return {"repo_path": dest}
    except subprocess.CalledProcessError as e:
        print(f"[clone_repo] Clone failed: {e.stderr}")
        # The graph routes an empty repo_path straight to `output`, so this is what the
        # dashboard shows instead of findings about some other codebase.
        return {"repo_path": "", "debug_findings": f"[clone_repo error] {e.stderr.strip()[-500:]}"}


def debug_agent(state: GraphState) -> dict:
    """Run the Alpha/Beta/Gamma investigation via IBM Bob CLI. See agents.investigator_agents."""
    return investigator_agents(state)


def documents(state: GraphState) -> dict:
    """Write the final bug-report via IBM Bob CLI. See agents.documenter_agent."""
    return documenter_agent(state)


def output(state: GraphState) -> dict:
    print("[output] Graph complete. Sending callback (stub)...")
    print(f"  callback_url : {state.get('callback_url', 'N/A')}")
    print(f"  is_flaky     : {state.get('is_flaky')}")
    print(f"  document     : {state.get('document')}")
    return {}
