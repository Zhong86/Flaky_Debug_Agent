import subprocess
import tempfile
from datetime import datetime

from core.config import get_settings
from graph.agents import documenter_agent, fixer_agent, investigator_agents
from graph.state import GraphState
from services.github_dispatch import rerun_and_wait


def check_flaky(state: GraphState) -> dict:
    results = state["rerun_results"]
    # flaky = failed at least once AND passed at least once across identical reruns
    is_flaky = any(0 < r["passed"] < r["attempts"] for r in results)
    return {"is_flaky": is_flaky}


def clone_repo(state: GraphState) -> dict:
    print("[clone_repo] Cloning repository for debug agent...")
    repository = state["github_payload"].get("repository")
    branch = state["github_payload"].get("branch")

    dest = tempfile.mkdtemp(prefix="flaky-debug-")
    # Public HTTPS clone for now — private repos will need the GitHub App's
    # installation token in the URL (x-access-token:<token>@github.com/...).
    repo_url = f"https://github.com/{repository}.git"

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, dest]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
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


def _git(repo_path: str, *args: str, config: dict[str, str] | None = None) -> str:
    cmd = ["git", "-C", repo_path]
    for key, value in (config or {}).items():
        cmd += ["-c", f"{key}={value}"]
    cmd += list(args)
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def code_fix(state: GraphState) -> dict:
    print("[code_fix] Delegating fix to IBM Bob CLI...")

    repo_path = state.get("repo_path")
    if not repo_path:
        print("[code_fix] No repo_path (clone_repo failed?) — skipping")
        return {"fix_applied": False}

    bob_result = fixer_agent(state)
    if not bob_result.get("fix_applied"):
        print("[code_fix] Bob did not produce a fix")
        return {"fix_applied": False}

    settings = get_settings()
    if not settings.github_token:
        print("[code_fix] No GITHUB_TOKEN — fix applied locally only, skipping push")
        return {"fix_applied": True}

    findings = state["debug_findings"]
    branch = f"flaky-fix/{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        _git(repo_path, "checkout", "-b", branch)
        _git(repo_path, "add", "-A")
        _git(repo_path, "commit", "-m", f"flaky-fix: {findings[:72]}", config=_BOT_IDENTITY)
        _git(
            repo_path,
            "push",
            "origin",
            branch,
            config={"http.extraheader": f"AUTHORIZATION: bearer {settings.github_token}"},
        )
        sha = _git(repo_path, "rev-parse", "HEAD")
    except subprocess.CalledProcessError as e:
        print(f"[code_fix] Commit/push failed: {e.stderr}")
        return {"fix_applied": False}

    print(f"[code_fix] Pushed {branch} -> {sha}")
    return {"fix_applied": True, "fix_branch": branch, "fix_sha": sha}


async def retest_flaky(state: GraphState) -> dict:
    print("[retest_flaky] Retesting flaky test...")

    if not get_settings().github_token:
        print("[retest_flaky] No GITHUB_TOKEN configured — falling back to stub")
        return {"retest_passed": True}

    payload = state["github_payload"]
    repo = payload.get("repository")
    # Prefer the fix branch code_fix actually pushed; fall back to the original
    # branch/sha when code_fix stayed in stub mode (no token, or nothing to commit).
    ref = state.get("fix_branch") or payload.get("branch") or "main"
    sha = state.get("fix_sha") or payload.get("sha") or ref
    test_ids = [r["test_id"] for r in state["rerun_results"]]

    results = await rerun_and_wait(repo, ref=ref, sha=sha, test_ids=test_ids)
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
