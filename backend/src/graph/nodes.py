import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from core.config import get_settings
from graph.state import GraphState
from services.github_dispatch import rerun_and_wait

# Project root is 3 levels up from this file:
# graph/ -> src/ -> backend/ -> <project root>
_PROJECT_ROOT = Path(__file__).parents[3]


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
    print("[debug_agent] Running multi-agent debug system (stub)...")
    print(f"[debug_agent] Reading checkout at {state.get('repo_path', 'N/A')}")
    findings = (
        "STUB: Root cause identified as a race condition in the test setup "
        "due to shared mutable state between test cases."
    )
    print(f"[debug_agent] debug_findings={findings!r}")
    return {"debug_findings": findings}


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
    print("[code_fix] Running Bob Agent mode to apply fix (stub)...")
    print(f"[code_fix] Applying fix based on findings: {state['debug_findings']!r}")

    repo_path = state.get("repo_path")
    settings = get_settings()
    if not settings.github_token or not repo_path:
        print("[code_fix] No GITHUB_TOKEN/repo_path — skipping real commit (stub)")
        return {"fix_applied": True}

    # Stub content — real file edits go here once the agent actually reasons
    # over the codebase; the git plumbing (branch, commit, push) is real either way.
    findings = state["debug_findings"]
    notes_path = Path(repo_path) / "FLAKY_FIX_NOTES.md"
    notes_path.write_text(
        f"# Flaky Fix (stub)\n\n## Debug findings\n{findings}\n\n"
        "Real fix content goes here once the agent actually edits source files.\n"
    )

    branch = f"flaky-fix/{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        _git(repo_path, "checkout", "-b", branch)
        _git(repo_path, "add", "FLAKY_FIX_NOTES.md")
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
    print("[documents] Generating findings document (stub LLM summary)...")
    subfolder = "success" if state["retest_passed"] else "fail"
    output_dir = _PROJECT_ROOT / "flaky_debug" / subfolder
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"report_{timestamp}.md"
    filepath = output_dir / filename

    # Stub LLM summary — real LLM call replaces this block
    content = f"""# Flaky Debug Report

**Generated:** {datetime.now().isoformat()}
**Outcome:** {subfolder.upper()}

## Debug Findings
{state.get('debug_findings', 'N/A')}

## Fix Applied
{state.get('fix_applied', False)}

## Retest Passed
{state.get('retest_passed', False)}

## GitHub Payload Summary
Repository: {state.get('github_payload', {}).get('repository', 'N/A')}
"""

    filepath.write_text(content)
    document_path = str(filepath)
    print(f"[documents] Written to {document_path}")
    return {"document": document_path}


def output(state: GraphState) -> dict:
    print("[output] Graph complete. Sending callback (stub)...")
    print(f"  callback_url : {state.get('callback_url', 'N/A')}")
    print(f"  is_flaky     : {state.get('is_flaky')}")
    print(f"  fix_applied  : {state.get('fix_applied')}")
    print(f"  retest_passed: {state.get('retest_passed')}")
    print(f"  document     : {state.get('document')}")
    return {}
