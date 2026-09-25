import os
from datetime import datetime
from pathlib import Path

from graph.state import GraphState

# Project root is 3 levels up from this file:
# graph/ -> src/ -> backend/ -> <project root>
_PROJECT_ROOT = Path(__file__).parents[3]


def check_flaky(state: GraphState) -> dict:
    print("[check_flaky] Running flakiness check (stub)...")
    # Hardcoded for development — real pytest-flaky call goes here
    is_flaky = True
    print(f"[check_flaky] is_flaky={is_flaky}")
    return {"is_flaky": is_flaky}


def debug_agent(state: GraphState) -> dict:
    print("[debug_agent] Running multi-agent debug system (stub)...")
    findings = (
        "STUB: Root cause identified as a race condition in the test setup "
        "due to shared mutable state between test cases."
    )
    print(f"[debug_agent] debug_findings={findings!r}")
    return {"debug_findings": findings}


def code_fix(state: GraphState) -> dict:
    print("[code_fix] Running Bob Agent mode to apply fix (stub)...")
    print(f"[code_fix] Applying fix based on findings: {state['debug_findings']!r}")
    fix_applied = True
    print(f"[code_fix] fix_applied={fix_applied}")
    return {"fix_applied": fix_applied}


def retest_flaky(state: GraphState) -> dict:
    print("[retest_flaky] Retesting flaky test (stub)...")
    # Hardcoded for development — real pytest rerun goes here
    retest_passed = True
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
