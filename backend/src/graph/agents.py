"""
agents.py -- LangGraph node functions for the Flaky Debug Agent.

Architecture
------------
The Python backend is a pure orchestrator.  All AI reasoning is delegated
to the local IBM Bob CLI (``bob run``) via ``call_ibm_bob_cli``.  Bob only
reads the watched repo and writes the report -- it never modifies the repo.
There are no LLM libraries, no Watsonx SDK, and no langchain imports
anywhere in this file.

Nodes
-----
investigator_agents(state)
    EXPLORE step, called from graph.nodes.debug_agent.  Builds one
    comprehensive prompt that instructs Bob to act as all three specialist
    personas simultaneously (Alpha load-tester, Beta delay-injector, Gamma
    order-shuffler).  Passes the CI logs, the async git diff of the repo
    clone_repo checked out, and the source of each flaky test file (derived
    from state["rerun_results"]) to Bob and stores the response in
    state["debug_findings"].  Runs Bob in "ask" mode -- pure read-only
    investigation, no Edit or Execute access.

documenter_agent(state)
    DOCUMENT step, called from graph.nodes.documents.  Runs Bob in "plan"
    mode (Edit, no Execute) with its workspace scoped to flaky_debug/reports/
    and asks it to write the bug-report markdown file directly at a path we
    hand it.  Sets state["document"] to that path.

IBM Bob CLI
-----------
All intelligence comes from ``bob run --mode <mode> ...`` run as a
subprocess.  See tools.call_ibm_bob_cli.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from graph.state import GraphState
from graph.tools import (
    call_ibm_bob_cli,
    filter_async_git_diff,
    read_source_code,
    report_dir,
)


# ---------------------------------------------------------------------------
# investigator_agents -- EXPLORE step
# ---------------------------------------------------------------------------


def investigator_agents(state: GraphState) -> dict:
    """Run the combined Alpha / Beta / Gamma investigation via IBM Bob CLI.

    Extracts repo context from the state, gathers the async git diff and
    the changed file's source, then builds one comprehensive prompt that
    asks Bob to play all three investigator roles simultaneously.

    Bob's response is stored verbatim as state["debug_findings"].
    """
    logs: str = state.get("logs", "")
    repo_path: str = state.get("repo_path") or "."
    rerun_results: list[dict] = state.get("rerun_results", [])

    # Gather read-only context to enrich the prompt.
    async_diff = filter_async_git_diff(repo_path)

    test_summary = "\n".join(
        f"  - {r['test_id']}: {r['passed']}/{r['attempts']} passed"
        for r in rerun_results
    ) or "(no rerun results provided)"

    # pytest-style IDs look like "path/to/test_file.py::test_name" -- read each
    # unique file referenced so Bob sees the actual flaky test source.
    test_files = sorted({
        r["test_id"].split("::")[0] for r in rerun_results if "::" in r["test_id"]
    })
    source_sections = "\n\n".join(
        f"--- {f} ---\n{read_source_code(str(Path(repo_path) / f))}" for f in test_files
    ) or "(no test files resolved from rerun results)"

    prompt = (
        "You are the Master Agent for a flaky-test debugging system.\n"
        "Please act simultaneously as all three specialist sub-agents:\n\n"
        "  - Alpha (Load/Stress Tester): Analyse the statistical failure rate "
        "visible in the rerun results below and identify burst-failure patterns.\n"
        "  - Beta (Delay Injector / TOCTOU Analyst): Examine the async git diff "
        "for race conditions and Time-of-Check-to-Time-of-Use windows. Propose "
        "the exact code locations where a sleep() injection would reliably "
        "reproduce the failure.\n"
        "  - Gamma (Order Shuffler / TOD Analyst): Identify global-state pollution, "
        "shared fixtures, or database leaks that make tests order-dependent.\n\n"
        "Produce a structured report with one section per sub-agent role.\n\n"
        "== REPOSITORY ==\n"
        f"Path: {repo_path}\n\n"
        "== FLAKY TEST RERUN RESULTS ==\n"
        f"{test_summary}\n\n"
        "== CI FAILURE LOGS ==\n"
        f"{logs or '(none provided)'}\n\n"
        "== ASYNC / CONCURRENCY GIT DIFF ==\n"
        f"{async_diff or '(no concurrency-related changes detected)'}\n\n"
        "== FLAKY TEST SOURCE ==\n"
        f"{source_sections}\n"
    )

    print(
        f"[investigator_agents] Calling bob (mode=ask) | "
        f"repo={repo_path} | tests={len(rerun_results)}"
    )

    debug_findings = call_ibm_bob_cli(prompt, repo_path=repo_path, mode="ask")

    print(
        f"[investigator_agents] Bob responded with "
        f"{len(debug_findings)} chars of findings."
    )

    return {"debug_findings": debug_findings}


# ---------------------------------------------------------------------------
# documenter_agent -- DOCUMENT step
# ---------------------------------------------------------------------------


def documenter_agent(state: GraphState) -> dict:
    """Ask IBM Bob CLI to write the final markdown bug-report directly.

    Runs Bob in "plan" mode (Edit, no Execute) with its workspace scoped to
    flaky_debug/reports/ and hands it the exact file path to create -- Bob
    writes the report itself instead of returning text for Python to persist.

    Sets state["document"] to the written file path.
    """
    github_payload: dict = state.get("github_payload", {})
    output_dir = report_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = output_dir / f"bug_report_{timestamp}.md"

    prompt = (
        "You are a technical writer for a software engineering team.\n"
        f"Create the file `{target_path.name}` with a concise, well-structured "
        "markdown bug report that a developer can immediately act on.  Include "
        "these sections:\n"
        "  1. Summary\n"
        "  2. Statistical Failure Baseline\n"
        "  3. Race Conditions Found\n"
        "  4. Test Order Dependencies Found\n"
        "  5. Recommendations\n\n"
        "== SESSION STATE ==\n"
        f"Repository   : {github_payload.get('repository', 'unknown')}\n"
        f"Rerun results: {state.get('rerun_results', [])}\n"
        f"Is flaky     : {state.get('is_flaky')}\n\n"
        "== INVESTIGATION FINDINGS ==\n"
        f"{state.get('debug_findings', '(none)')}\n\n"
        "== CI LOGS ==\n"
        f"{state.get('logs', '(none)')}\n"
    )

    print(f"[documenter_agent] Calling bob (mode=plan) | target={target_path}")

    response = call_ibm_bob_cli(prompt, repo_path=str(output_dir), mode="plan")

    if response.startswith("[bobshell error]"):
        print(f"[documenter_agent] Bob CLI error: {response[:200]}")
        return {"document": response}

    if not target_path.exists():
        print(f"[documenter_agent] Bob did not create {target_path}")
        return {"document": f"[documenter_agent error] {target_path} was not created"}

    print(f"[documenter_agent] Document written to: {target_path}")
    return {"document": str(target_path)}
