"""
agents.py — IBM Watsonx LLM agent nodes for the Flaky Debug Agent.

Architecture
------------
Two modes reflect the "Explore → General" sub-agent philosophy:

  EXPLORE (read-only)
    investigator_agents(state)
        Runs three specialised LLM sub-agents in parallel via
        ThreadPoolExecutor.  Each is bound ONLY to read-only tools so it
        cannot modify the repository.

          Alpha — Load/Stress Tester
              Calls run_generic_test with iterations=50 to establish the
              exact statistical failure-rate baseline of the flaky test.

          Beta — Delay Injector (TOCTOU Analyst)
              Uses read_source_code + filter_async_git_diff to locate
              concurrency hotspots.  Proposes where microsecond sleeps
              should be injected to predictably force race conditions.

          Gamma — Order Shuffler (TOD Analyst)
              Focuses on Test Order Dependency: searches for global-state
              pollution, database configuration leaks, and shared fixtures
              between test cases.

        All three findings are merged into state["debug_findings"].

  GENERAL (write)
    fixer_agent(state)
        Reads the combined Alpha + Beta + Gamma findings from
        state["debug_findings"] and applies a production-grade fix via
        write_fixed_code.  Sets state["fix_applied"] = True.

    documenter_agent(state)
        Reads the full state, produces a polished markdown report, and
        calls create_markdown_docs to persist it.  Sets state["document"]
        to the written file path.

LLM
---
IBM Watsonx via langchain_ibm.ChatWatsonx.  Credentials are read from
environment variables:
  WATSONX_URL        — e.g. "https://us-south.ml.cloud.ibm.com"
  WATSONX_APIKEY     — IBM Cloud API key
  WATSONX_PROJECT_ID — Watsonx project id
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_ibm import ChatWatsonx

from graph.state import GraphState
from graph.tools import (
    create_markdown_docs,
    filter_async_git_diff,
    read_source_code,
    run_generic_test,
    write_fixed_code,
)

# ---------------------------------------------------------------------------
# Watsonx LLM factory
# ---------------------------------------------------------------------------

_WATSONX_URL = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
_WATSONX_APIKEY = os.getenv("WATSONX_APIKEY", "")
_WATSONX_PROJECT_ID = os.getenv("WATSONX_PROJECT_ID", "")

# Lightweight model for investigation (three parallel instances).
_EXPLORE_MODEL = "ibm/granite-3-3-8b-instruct"
# More capable model for writing code and documentation.
_GENERAL_MODEL = "ibm/granite-3-3-8b-instruct"


def _make_llm(model_id: str, **params: Any) -> ChatWatsonx:
    """Return a ChatWatsonx instance for *model_id*."""
    return ChatWatsonx(
        model_id=model_id,
        url=_WATSONX_URL,
        apikey=_WATSONX_APIKEY,
        project_id=_WATSONX_PROJECT_ID,
        params={
            "max_new_tokens": 1024,
            "temperature": 0.1,
            **params,
        },
    )


# ---------------------------------------------------------------------------
# Core helper: agentic tool-call loop
# ---------------------------------------------------------------------------


def _run_tool_agent(
    llm: ChatWatsonx,
    tools: list,
    system_prompt: str,
    human_prompt: str,
    max_rounds: int = 6,
) -> str:
    """Bind *tools* to *llm*, drive the tool-call loop, return final text.

    Handles multi-round tool calls: after each LLM response that contains
    tool_calls, every requested tool is executed and the results are fed
    back as ToolMessages before the next LLM call.  The loop exits when the
    model returns a plain text response (no more tool calls) or after
    *max_rounds* iterations.
    """
    bound = llm.bind_tools(tools)
    tool_map = {t.name: t for t in tools}
    messages: list = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt),
    ]

    response = None
    for _ in range(max_rounds):
        response = bound.invoke(messages)
        messages.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            break  # plain-text answer — we are done

        for tc in tool_calls:
            tool_name: str = tc["name"]
            tool_args: dict = tc["args"]
            if tool_name in tool_map:
                try:
                    result = tool_map[tool_name].invoke(tool_args)
                except Exception as exc:  # noqa: BLE001
                    result = f"[tool error] {exc}"
            else:
                result = f"[unknown tool: {tool_name}]"

            messages.append(
                ToolMessage(content=str(result), tool_call_id=tc["id"])
            )

    return str(response.content) if response is not None else ""


# ---------------------------------------------------------------------------
# Sub-agent definitions (EXPLORE mode)
# ---------------------------------------------------------------------------


def _alpha_load_tester(
    llm: ChatWatsonx,
    repo_path: str,
    test_command: str,
    logs: str,
) -> str:
    """Subagent Alpha — Load/Stress Tester.

    Runs the test suite 50 times to establish the precise statistical
    failure-rate baseline of the suspected flaky test.
    """
    system_prompt = (
        "You are Subagent Alpha, a load-testing and statistical analysis expert. "
        "Your only job is to determine the exact flakiness rate of a test suite "
        "by running it many times and analysing the results.\n\n"
        "You have one tool: run_generic_test.\n"
        "Call it with iterations=50 to gather enough data for statistical significance. "
        "Then calculate:\n"
        "  • Failure rate (failures / total runs as a percentage)\n"
        "  • Whether failures cluster in time (burst failures vs random scatter)\n"
        "  • Any patterns visible in the stdout/stderr of failed runs\n\n"
        "Return a concise, structured report. Be quantitative — cite exact numbers."
    )
    human_prompt = (
        f"Repository: {repo_path}\n"
        f"Test command: {test_command}\n\n"
        f"CI Logs (last failure):\n{logs or '(none provided)'}\n\n"
        f"Call run_generic_test(repo_path='{repo_path}', "
        f"test_command='{test_command}', iterations=50) and report the "
        "statistical failure baseline."
    )
    return _run_tool_agent(
        llm,
        [run_generic_test],          # Alpha: ONLY the stress-test tool
        system_prompt,
        human_prompt,
    )


def _beta_delay_injector(
    llm: ChatWatsonx,
    repo_path: str,
    changed_file: str,
    logs: str,
) -> str:
    """Subagent Beta — Delay Injector / TOCTOU Analyst.

    Reads the changed source file and the async-filtered git diff to find
    Time-of-Check to Time-of-Use (TOCTOU) race conditions.  Proposes
    exact locations where microsecond sleep() injections would reliably
    trigger the failure on demand.
    """
    system_prompt = (
        "You are Subagent Beta, an expert in concurrency bugs and race conditions. "
        "You specialise in Time-of-Check to Time-of-Use (TOCTOU) analysis.\n\n"
        "You have two read-only tools:\n"
        "  • read_source_code — reads the full text of a source file.\n"
        "  • filter_async_git_diff — shows only concurrency-related diff hunks.\n\n"
        "Your analysis must:\n"
        "1. Read the changed file to understand its structure.\n"
        "2. Read the async diff to see what changed.\n"
        "3. Identify every code location where a thread/goroutine/promise switch "
        "could occur between a check and a use of a shared resource.\n"
        "4. Propose exactly where a sleep() / time.Sleep() / setTimeout() "
        "injection (microseconds to milliseconds) would predictably force "
        "the race to surface.\n\n"
        "Be specific — cite file, line number, and the exact code to inject."
    )
    human_prompt = (
        f"Repository: {repo_path}\n"
        f"Changed file: {changed_file or '(unknown)'}\n\n"
        f"CI Logs:\n{logs or '(none provided)'}\n\n"
        "Step 1: Call read_source_code to read the changed file.\n"
        f"Step 2: Call filter_async_git_diff(repo_path='{repo_path}') to see "
        "what concurrency code changed.\n"
        "Step 3: Identify TOCTOU windows and propose delay injection points."
    )
    return _run_tool_agent(
        llm,
        [read_source_code, filter_async_git_diff],   # Beta: source + diff only
        system_prompt,
        human_prompt,
    )


def _gamma_order_shuffler(
    llm: ChatWatsonx,
    repo_path: str,
    changed_file: str,
    logs: str,
) -> str:
    """Subagent Gamma — Order Shuffler / Test Order Dependency (TOD) Analyst.

    Reads the source to identify global/module-level mutable state, shared
    database configurations, or fixture leakage that makes test outcome
    depend on execution order.
    """
    system_prompt = (
        "You are Subagent Gamma, an expert in Test Order Dependency (TOD) bugs. "
        "You specialise in finding global-state pollution, database configuration "
        "leaks, and shared fixture side-effects that make tests pass or fail "
        "depending on execution order.\n\n"
        "You have one read-only tool: read_source_code.\n\n"
        "Your analysis must identify:\n"
        "1. Module-level or class-level mutable variables that survive between tests.\n"
        "2. setUp/tearDown (or before/after) methods that do not fully reset state.\n"
        "3. Database, cache, or filesystem resources not isolated per test.\n"
        "4. Any use of module-level singletons, connection pools, or caches that "
        "could carry state from one test to the next.\n\n"
        "For each finding state: what the polluting variable/resource is, which "
        "tests are affected, and what cleanup is needed."
    )
    human_prompt = (
        f"Repository: {repo_path}\n"
        f"Changed file: {changed_file or '(unknown)'}\n\n"
        f"CI Logs:\n{logs or '(none provided)'}\n\n"
        f"Call read_source_code(file_path='{changed_file}') and analyse the code "
        "for Test Order Dependency issues."
    )
    return _run_tool_agent(
        llm,
        [read_source_code],          # Gamma: source reading only
        system_prompt,
        human_prompt,
    )


# ---------------------------------------------------------------------------
# EXPLORE MODE — investigator_agents
# ---------------------------------------------------------------------------


def investigator_agents(state: GraphState) -> dict:
    """Run Alpha, Beta, and Gamma sub-agents concurrently (read-only).

    All three agents execute in a ThreadPoolExecutor and are bound strictly
    to read-only tools — write tools are never passed.  Their findings are
    merged into a structured markdown block stored in state["debug_findings"].
    """
    github_payload: dict = state.get("github_payload", {})
    logs: str = state.get("logs", "")
    repo_path: str = github_payload.get("repo_path", ".")
    changed_file: str = github_payload.get("changed_file", "")
    test_command: str = state.get("test_command", github_payload.get("test_command", "pytest"))

    # Each sub-agent gets its own LLM instance — safe for concurrent use.
    llm_alpha = _make_llm(_EXPLORE_MODEL)
    llm_beta = _make_llm(_EXPLORE_MODEL)
    llm_gamma = _make_llm(_EXPLORE_MODEL)

    print(
        f"[investigator_agents] Launching Alpha/Beta/Gamma in parallel | "
        f"repo={repo_path} | cmd={test_command} | file={changed_file or '(unknown)'}"
    )

    findings: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=3) as pool:
        future_map = {
            pool.submit(_alpha_load_tester, llm_alpha, repo_path, test_command, logs): "alpha",
            pool.submit(_beta_delay_injector, llm_beta, repo_path, changed_file, logs): "beta",
            pool.submit(_gamma_order_shuffler, llm_gamma, repo_path, changed_file, logs): "gamma",
        }
        for future in as_completed(future_map):
            agent_name = future_map[future]
            try:
                findings[agent_name] = future.result()
                print(
                    f"[investigator_agents] {agent_name.upper()} completed "
                    f"({len(findings[agent_name])} chars)"
                )
            except Exception as exc:  # noqa: BLE001
                findings[agent_name] = f"[{agent_name} error] {exc}"
                print(f"[investigator_agents] {agent_name.upper()} FAILED: {exc}")

    debug_findings = (
        "## Investigator Findings\n\n"
        "### Subagent Alpha — Load/Stress Tester\n"
        f"{findings.get('alpha', '(no output)')}\n\n"
        "---\n\n"
        "### Subagent Beta — Delay Injector (TOCTOU Analysis)\n"
        f"{findings.get('beta', '(no output)')}\n\n"
        "---\n\n"
        "### Subagent Gamma — Order Shuffler (TOD Analysis)\n"
        f"{findings.get('gamma', '(no output)')}"
    )

    print(
        f"[investigator_agents] All sub-agents done. "
        f"debug_findings={len(debug_findings)} chars"
    )
    return {"debug_findings": debug_findings}


# ---------------------------------------------------------------------------
# GENERAL MODE — fixer_agent
# ---------------------------------------------------------------------------


def fixer_agent(state: GraphState) -> dict:
    """Apply a production-grade fix based on Alpha + Beta + Gamma findings.

    Reads ``debug_findings`` (containing all three sub-agent reports) and
    the current source file.  Asks the LLM for the minimal correct fix that
    addresses all identified root causes, then calls ``write_fixed_code`` to
    persist it.  Sets ``fix_applied`` to True on success.
    """
    debug_findings: str = state.get("debug_findings", "")
    github_payload: dict = state.get("github_payload", {})
    changed_file: str = github_payload.get("changed_file", "")

    if not changed_file:
        print("[fixer_agent] No changed_file in payload — skipping fix.")
        return {"fix_applied": False}

    try:
        current_code = Path(changed_file).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[fixer_agent] Cannot read {changed_file}: {exc}")
        return {"fix_applied": False}

    llm_general = _make_llm(_GENERAL_MODEL)

    system_prompt = (
        "You are an expert software engineer proficient in Python, Java, "
        "JavaScript/TypeScript, and Go.  You will receive:\n"
        "1. A combined bug report from three specialised investigators:\n"
        "   • Alpha: statistical failure-rate data from 50 test runs.\n"
        "   • Beta: TOCTOU race-condition analysis with delay injection points.\n"
        "   • Gamma: Test Order Dependency analysis of global-state pollution.\n"
        "2. The current source code of the affected file.\n\n"
        "Your task:\n"
        "• Synthesise all three reports to understand the complete root cause.\n"
        "• Produce a MINIMAL, correct fix that eliminates flakiness permanently.\n"
        "• Address concurrency issues (Beta) AND state isolation (Gamma).\n"
        "• Do NOT refactor unrelated code.\n"
        "• Call write_fixed_code with the corrected full file content.\n"
        "• After calling the tool, write a 3-5 sentence summary of every "
        "change made and the reasoning behind each one."
    )
    human_prompt = (
        f"## Combined Investigator Report\n{debug_findings}\n\n"
        f"## Current source: {changed_file}\n"
        f"```\n{current_code}\n```\n\n"
        "Synthesise all findings and call write_fixed_code with the fixed file."
    )

    response = _run_tool_agent(llm_general, [write_fixed_code], system_prompt, human_prompt)
    print(f"[fixer_agent] Fix applied to {changed_file}. Summary: {response[:160]}")
    return {"fix_applied": True}


# ---------------------------------------------------------------------------
# GENERAL MODE — documenter_agent
# ---------------------------------------------------------------------------


def documenter_agent(state: GraphState) -> dict:
    """Generate and persist a markdown bug-report for this debug session.

    Reads the full state, produces a structured markdown document via the
    LLM, then persists it with ``create_markdown_docs``.  Sets
    ``document`` to the path of the written file.
    """
    llm_general = _make_llm(_GENERAL_MODEL)
    github_payload: dict = state.get("github_payload", {})

    system_prompt = (
        "You are a technical writer.  Produce a concise, well-structured "
        "markdown bug report that a developer could immediately act on.  "
        "Include these sections:\n"
        "  1. Summary\n"
        "  2. Statistical Failure Baseline (from Alpha)\n"
        "  3. Race Conditions Found (from Beta)\n"
        "  4. Test Order Dependencies Found (from Gamma)\n"
        "  5. Fix Applied\n"
        "  6. Retest Outcome\n"
        "  7. Recommendations\n\n"
        "Then call create_markdown_docs with your completed report."
    )
    human_prompt = (
        "## Session State\n"
        f"- Repository   : {github_payload.get('repo_path', 'unknown')}\n"
        f"- Changed file : {github_payload.get('changed_file', 'unknown')}\n"
        f"- Test command : {state.get('test_command', github_payload.get('test_command', 'unknown'))}\n"
        f"- Is flaky     : {state.get('is_flaky')}\n"
        f"- Fix applied  : {state.get('fix_applied')}\n"
        f"- Retest passed: {state.get('retest_passed')}\n\n"
        "## Combined Investigator Findings\n"
        f"{state.get('debug_findings', '(none)')}\n\n"
        "## CI Logs\n"
        f"{state.get('logs', '(none)')}\n\n"
        "Write the full bug report and call create_markdown_docs."
    )

    response = _run_tool_agent(llm_general, [create_markdown_docs], system_prompt, human_prompt)

    # Extract the file path from the tool's return value embedded in the response.
    document_path = ""
    for line in reversed(response.splitlines()):
        stripped = line.strip()
        if stripped.endswith(".md") and ("/" in stripped or "\\" in stripped):
            document_path = stripped
            break

    print(f"[documenter_agent] Document written to: {document_path or '(unknown)'}")
    return {"document": document_path or response}
