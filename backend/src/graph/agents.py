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
    EXPLORE step.  Builds one comprehensive prompt that instructs Bob to
    act as all three specialist personas simultaneously (Alpha load-tester,
    Beta delay-injector, Gamma order-shuffler).  Passes the CI logs, the
    async git diff, and the changed file's source code to Bob and stores
    the response in state["debug_findings"].

fixer_agent(state)
    FIX step.  Builds a fix prompt from the debug_findings (flaky path) or
    raw CI logs (deterministic path) and tells Bob to apply the minimal
    code change directly.  Sets state["fix_applied"] = True on success.

documenter_agent(state)
    DOCUMENT step.  Asks Bob to write a structured markdown bug-report from
    the full session state and persists it with create_markdown_docs.
    Sets state["document"] to the written file path.

IBM Bob CLI
-----------
All intelligence comes from ``bobshell --prompt "<prompt>"`` run as a
subprocess inside the repository directory.  See tools.call_ibm_bob_cli.
"""

from __future__ import annotations

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
    github_payload: dict = state.get("github_payload", {})
    logs: str = state.get("logs", "")
    repo_path: str = github_payload.get("repo_path", ".")
    changed_file: str = github_payload.get("changed_file", "")
    test_command: str = github_payload.get("test_command", "pytest")

    # Gather read-only context to enrich the prompt.
    async_diff = filter_async_git_diff(repo_path)
    source_code = read_source_code(changed_file) if changed_file else "(no file specified)"

    prompt = (
        "You are the Master Agent for a flaky-test debugging system.\n"
        "Please act simultaneously as all three specialist sub-agents:\n\n"
        "  - Alpha (Load/Stress Tester): Analyse the statistical failure rate "
        "visible in the CI logs below and identify burst-failure patterns.\n"
        "  - Beta (Delay Injector / TOCTOU Analyst): Examine the async git diff "
        "for race conditions and Time-of-Check-to-Time-of-Use windows. Propose "
        "the exact code locations where a sleep() injection would reliably "
        "reproduce the failure.\n"
        "  - Gamma (Order Shuffler / TOD Analyst): Identify global-state pollution, "
        "shared fixtures, or database leaks that make tests order-dependent.\n\n"
        "Produce a structured report with one section per sub-agent role.\n\n"
        "== REPOSITORY ==\n"
        f"Path        : {repo_path}\n"
        f"Changed file: {changed_file or '(unknown)'}\n"
        f"Test command: {test_command}\n\n"
        "== CI FAILURE LOGS ==\n"
        f"{logs or '(none provided)'}\n\n"
        "== ASYNC / CONCURRENCY GIT DIFF ==\n"
        f"{async_diff or '(no concurrency-related changes detected)'}\n\n"
        "== SOURCE CODE ==\n"
        f"{source_code}\n"
    )

    print(
        f"[investigator_agents] Calling bobshell | "
        f"repo={repo_path} | file={changed_file or 'N/A'}"
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
    ``fix_applied`` -- set to True when bobshell exits successfully.
    """
    github_payload: dict = state.get("github_payload", {})
    logs: str = state.get("logs", "")
    is_flaky: bool = state.get("is_flaky", False)
    debug_findings: str = state.get("debug_findings", "")
    repo_path: str = github_payload.get("repo_path", ".")
    changed_file: str = github_payload.get("changed_file", "")
    test_command: str = github_payload.get("test_command", "pytest")

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
        f"Changed file: {changed_file or '(unknown)'}\n"
        f"Test command: {test_command}\n\n"
        f"{context_section}\n"
    )

    print(
        f"[fixer_agent] Calling bobshell | "
        f"mode={'flaky' if is_flaky else 'deterministic'} | "
        f"repo={repo_path} | file={changed_file or 'N/A'}"
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
    persists it under flaky_debug/reports/.

    Sets state["document"] to the written file path.
    """
    github_payload: dict = state.get("github_payload", {})
    repo_path: str = github_payload.get("repo_path", ".")

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
        f"Repository   : {github_payload.get('repo_path', 'unknown')}\n"
        f"Changed file : {github_payload.get('changed_file', 'unknown')}\n"
        f"Test command : {github_payload.get('test_command', 'unknown')}\n"
        f"Is flaky     : {state.get('is_flaky')}\n"
        f"Fix applied  : {state.get('fix_applied')}\n"
        f"Retest passed: {state.get('retest_passed')}\n\n"
        "== INVESTIGATION FINDINGS ==\n"
        f"{state.get('debug_findings', '(none)')}\n\n"
        "== CI LOGS ==\n"
        f"{state.get('logs', '(none)')}\n"
    )

    print(f"[documenter_agent] Calling bobshell for bug report | repo={repo_path}")

    response = call_ibm_bob_cli(prompt, repo_path=repo_path)

    if response.startswith("[bobshell error]"):
        print(f"[documenter_agent] Bob CLI error: {response[:200]}")
        document_path = response
    else:
        document_path = create_markdown_docs(response)
        print(f"[documenter_agent] Document written to: {document_path}")

    return {"document": document_path}
