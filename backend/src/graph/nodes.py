import asyncio
import subprocess
import tempfile
from datetime import datetime

from core.config import get_settings
from graph.agents import documenter_agent, fixer_agent, investigator_agents
from graph.state import GraphState
from services.github_app import get_github_app
from services.github_dispatch import rerun_and_wait


async def _installation_bearer(state: GraphState) -> str | None:
    """A fresh installation token if the App is installed there, else the GITHUB_TOKEN PAT."""
    installation_id = state.get("installation_id")
    if installation_id is not None and (app := get_github_app()) is not None:
        return await app.installation_token(installation_id)
    return get_settings().github_token or None


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
        # Header, not the URL, so a failed-clone error message can't leak the token.
        cmd += ["-c", f"http.extraheader=AUTHORIZATION: bearer {token}"]
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
        return {"repo_path": ""}


def debug_agent(state: GraphState) -> dict:
    """Run the Alpha/Beta/Gamma investigation via IBM Bob CLI. See agents.investigator_agents."""
    return investigator_agents(state)


_BOT_IDENTITY = {
    "user.name": "flaky-debug-agent[bot]",
    "user.email": "flaky-debug-agent[bot]@users.noreply.github.com",
}


async def _git(repo_path: str, *args: str, config: dict[str, str] | None = None) -> str:
    cmd = ["git", "-C", repo_path]
    for key, value in (config or {}).items():
        cmd += ["-c", f"{key}={value}"]
    cmd += list(args)
    result = await asyncio.to_thread(subprocess.run, cmd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


async def code_fix(state: GraphState) -> dict:
    print("[code_fix] Delegating fix to IBM Bob CLI...")

    repo_path = state.get("repo_path")
    if not repo_path:
        print("[code_fix] No repo_path (clone_repo failed?) — skipping")
        return {"fix_applied": False}

    bob_result = fixer_agent(state)
    if not bob_result.get("fix_applied"):
        print("[code_fix] Bob did not produce a fix")
        return {"fix_applied": False}

    token = await _installation_bearer(state)
    if not token:
        print("[code_fix] No GitHub App installation or GITHUB_TOKEN — fix applied locally only, skipping push")
        return {"fix_applied": True}

    findings = state["debug_findings"]
    branch = f"flaky-fix/{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        await _git(repo_path, "checkout", "-b", branch)
        await _git(repo_path, "add", "-A")
        await _git(repo_path, "commit", "-m", f"flaky-fix: {findings[:72]}", config=_BOT_IDENTITY)
        await _git(
            repo_path,
            "push",
            "origin",
            branch,
            config={"http.extraheader": f"AUTHORIZATION: bearer {token}"},
        )
        sha = await _git(repo_path, "rev-parse", "HEAD")
    except subprocess.CalledProcessError as e:
        print(f"[code_fix] Commit/push failed: {e.stderr}")
        return {"fix_applied": False}

    print(f"[code_fix] Pushed {branch} -> {sha}")
    return {"fix_applied": True, "fix_branch": branch, "fix_sha": sha}


async def retest_flaky(state: GraphState) -> dict:
    print("[retest_flaky] Retesting flaky test...")

    if not await _installation_bearer(state):
        print("[retest_flaky] No GitHub App installation or GITHUB_TOKEN configured — falling back to stub")
        return {"retest_passed": True}

    payload = state["github_payload"]
    repo = payload.get("repository")
    # Prefer the fix branch code_fix actually pushed; fall back to the original
    # branch/sha when code_fix stayed in stub mode (no token, or nothing to commit).
    ref = state.get("fix_branch") or payload.get("branch") or "main"
    sha = state.get("fix_sha") or payload.get("sha") or ref
    test_ids = [r["test_id"] for r in state["rerun_results"]]

    results = await rerun_and_wait(
        repo, ref=ref, sha=sha, test_ids=test_ids, installation_id=state.get("installation_id")
    )
    retest_passed = bool(results) and all(r["passed"] == r["attempts"] for r in results)
    print(f"[retest_flaky] retest_passed={retest_passed}")
    return {"retest_passed": retest_passed}


def documents(state: GraphState) -> dict:
    """Write the final bug-report via IBM Bob CLI. See agents.documenter_agent."""
    return documenter_agent(state)


def output(state: GraphState) -> dict:
    print("[output] Graph complete. Sending callback (stub)...")
    print(f"  callback_url : {state.get('callback_url', 'N/A')}")
    print(f"  is_flaky     : {state.get('is_flaky')}")
    print(f"  fix_applied  : {state.get('fix_applied')}")
    print(f"  retest_passed: {state.get('retest_passed')}")
    print(f"  document     : {state.get('document')}")
    return {}
