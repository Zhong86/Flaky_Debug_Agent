"""
agents.py -- LangGraph node functions for the Flaky Debug Agent.

Architecture
------------
The Python backend is a pure orchestrator.  All AI reasoning and code
modification is delegated to the local IBM Bob CLI (bobshell) via
``call_ibm_bob_cli``.  There are no LLM libraries, no Watsonx SDK, and
no langchain imports anywhere in this file.

Nodes
-----
investigator_agents(state)
    EXPLORE step, called from graph.nodes.debug_agent.  Builds one
    comprehensive prompt that instructs Bob to act as all three specialist
    personas simultaneously (Alpha load-tester, Beta delay-injector, Gamma
    order-shuffler).  Passes the CI logs, the async git diff of the repo
    clone_repo checked out, and the source of each flaky test file (derived
    from state["rerun_results"]) to Bob and stores the response in
    state["debug_findings"].

fixer_agent(state)
    FIX step, called from graph.nodes.code_fix.  Builds a fix prompt from
    the debug_findings (flaky path) or raw CI logs (deterministic path) and
    tells Bob to apply the minimal code change directly inside
    state["repo_path"].  Sets state["fix_applied"] = True on success; the
    git branch/commit/push plumbing lives in graph.nodes.code_fix, not here.

documenter_agent(state)
    DOCUMENT step, called from graph.nodes.documents.  Asks Bob to write a
    structured markdown bug-report from the full session state and persists
    it with create_markdown_docs under flaky_debug/success or flaky_debug/fail
    depending on state["retest_passed"].  Sets state["document"] to the
    written file path.

IBM Bob CLI
-----------
All intelligence comes from ``bobshell --prompt "<prompt>"`` run as a
subprocess inside the repository directory.  See tools.call_ibm_bob_cli.
"""

from __future__ import annotations

from pathlib import Path

from graph.state import GraphState
from graph.tools import (
    call_ibm_bob_cli,
    create_markdown_docs,
    filter_async_git_diff,
    read_source_code,
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
        f"[investigator_agents] Calling bobshell | "
        f"repo={repo_path} | tests={len(rerun_results)}"
    )

    debug_findings = call_ibm_bob_cli(prompt, repo_path=repo_path)

    print(
        f"[investigator_agents] Bob responded with "
        f"{len(debug_findings)} chars of findings."
    )

    return {"debug_findings": debug_findings}


# ---------------------------------------------------------------------------
# fixer_agent -- FIX step
# ---------------------------------------------------------------------------


def fixer_agent(state: GraphState) -> dict:
    """Delegate code fixing to IBM Bob CLI.

    Builds a fix prompt and passes it to ``bobshell``.  Bob is responsible
    for reading the relevant files and applying the minimal correct change
    directly inside the repository working directory.

    Two source modes
    ----------------
    ``is_flaky == True``
        Bob receives the full Alpha / Beta / Gamma debug_findings so it can
        apply a targeted, evidence-based fix.

    ``is_flaky == False``
        The failure is deterministic.  Bob receives the raw CI logs and is
        summoned immediately -- no prior investigation output is available.

    State updates
    -------------
    ``fix_applied`` -- set to True when bobshell exits successfully.  The
    caller (graph.nodes.code_fix) is responsible for committing and pushing
    whatever Bob changed inside state["repo_path"].
    """
    logs: str = state.get("logs", "")
    is_flaky: bool = state.get("is_flaky", False)
    debug_findings: str = state.get("debug_findings", "")
    repo_path: str = state.get("repo_path") or "."
    rerun_results: list[dict] = state.get("rerun_results", [])
    test_ids = ", ".join(r["test_id"] for r in rerun_results) or "(unknown)"

    if is_flaky:
        context_section = (
            "== INVESTIGATION FINDINGS (Alpha / Beta / Gamma) ==\n"
            f"{debug_findings or '(no findings available)'}"
        )
        instruction = (
            "The test suite was confirmed **flaky** (intermittent failures). "
            "Three specialist sub-agents have investigated the root cause above. "
            "Apply the minimal code fix that permanently eliminates the flakiness. "
            "Do NOT refactor unrelated code."
        )
    else:
        context_section = (
            "== CI FAILURE LOGS ==\n"
            f"{logs or '(none provided)'}"
        )
        instruction = (
            "The CI pipeline failed with a **deterministic** (non-flaky) error. "
            "Review the logs above and apply the minimal fix directly."
        )

    prompt = (
        "You are the Master Agent for a flaky-test debugging system.\n"
        f"{instruction}\n\n"
        f"Repository  : {repo_path}\n"
        f"Flaky tests : {test_ids}\n\n"
        f"{context_section}\n"
    )

    print(
        f"[fixer_agent] Calling bobshell | "
        f"mode={'flaky' if is_flaky else 'deterministic'} | repo={repo_path}"
    )

    response = call_ibm_bob_cli(prompt, repo_path=repo_path)
    fix_applied = not response.startswith("[bobshell error]")

    if fix_applied:
        print(f"[fixer_agent] Bob applied the fix. Response length: {len(response)} chars.")
    else:
        print(f"[fixer_agent] Bob CLI returned an error:\n{response[:300]}")

    return {"fix_applied": fix_applied}


# ---------------------------------------------------------------------------
# documenter_agent -- DOCUMENT step
# ---------------------------------------------------------------------------


def documenter_agent(state: GraphState) -> dict:
    """Ask IBM Bob CLI to write the final markdown bug-report.

    Builds a prompt from the full session state and calls bobshell.
    Bob's response is passed directly to create_markdown_docs which
    persists it under flaky_debug/success/ or flaky_debug/fail/ depending
    on state["retest_passed"].

    Sets state["document"] to the written file path.
    """
    repo_path: str = state.get("repo_path") or "."
    github_payload: dict = state.get("github_payload", {})

    prompt = (
        "You are a technical writer for a software engineering team.\n"
        "Write a concise, well-structured markdown bug report that a developer "
        "can immediately act on.  Include these sections:\n"
        "  1. Summary\n"
        "  2. Statistical Failure Baseline\n"
        "  3. Race Conditions Found\n"
        "  4. Test Order Dependencies Found\n"
        "  5. Fix Applied\n"
        "  6. Retest Outcome\n"
        "  7. Recommendations\n\n"
        "== SESSION STATE ==\n"
        f"Repository   : {github_payload.get('repository', 'unknown')}\n"
        f"Rerun results: {state.get('rerun_results', [])}\n"
        f"Is flaky     : {state.get('is_flaky')}\n"
        f"Fix applied  : {state.get('fix_applied')}\n"
        f"Fix branch   : {state.get('fix_branch') or '(none)'}\n"
        f"Retest passed: {state.get('retest_passed')}\n\n"
        "== INVESTIGATION FINDINGS ==\n"
        f"{state.get('debug_findings', '(none)')}\n\n"
        "== CI LOGS ==\n"
        f"{state.get('logs', '(none)')}\n"
    )

    print(f"[documenter_agent] Calling bobshell for bug report | repo={repo_path}")

    response = call_ibm_bob_cli(prompt, repo_path=repo_path)
    subfolder = "success" if state.get("retest_passed") else "fail"

    if response.startswith("[bobshell error]"):
        print(f"[documenter_agent] Bob CLI error: {response[:200]}")
        document_path = response
    else:
        document_path = create_markdown_docs(response, subfolder=subfolder)
        print(f"[documenter_agent] Document written to: {document_path}")

    return {"document": document_path}
