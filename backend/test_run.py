# -*- coding: utf-8 -*-
"""
test_run.py -- Local smoke-test for investigator_agents and fixer_agent.

Run from the `backend/` directory:

    python test_run.py

Prerequisites
-------------
1. Install project dependencies (from backend/):
       uv sync
   or:
       pip install -e ".[dev]"

2. The IBM Bob CLI must be installed and on PATH:
       bobshell --version

   All AI reasoning (investigation + fixing + documentation) is delegated
   to bobshell as a subprocess.  No Watsonx API keys are required.

What this script does
---------------------
Step 1  Bootstrap sys.path so graph.* imports resolve from backend/src/
Step 2  Build a mock GraphState with is_flaky=True and simulated CI logs
Step 3  Call investigator_agents(state)  -- Bob acts as Alpha+Beta+Gamma
Step 4  Merge findings into state
Step 5  Call fixer_agent(state)          -- Bob applies the fix directly
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Path bootstrap — make `graph.*` importable from backend/src/
# ---------------------------------------------------------------------------
_BACKEND_SRC = Path(__file__).parent / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

# ---------------------------------------------------------------------------
# 2. Import agents  (deferred until after sys.path is set)
# ---------------------------------------------------------------------------
from graph.agents import fixer_agent, investigator_agents  # noqa: E402
from graph.state import GraphState  # noqa: E402

# ---------------------------------------------------------------------------
# 3. Build the mock GraphState
# ---------------------------------------------------------------------------
MOCK_LOGS = textwrap.dedent("""\
    ============================= test session starts ==============================
    platform linux -- Python 3.11.8, pytest-7.4.3, pluggy-1.3.0
    collected 3 items

    tests/test_cache.py::test_concurrent_write PASSED
    tests/test_cache.py::test_concurrent_write FAILED
    tests/test_cache.py::test_read_after_write ERROR

    =================================== FAILURES ===================================
    __________________ test_concurrent_write ___________________________________
    E   TimeoutError: lock acquisition timed out after 5.00s
    E   The test passed on attempt 1 but failed on attempt 2 (race condition suspected).
    E   Thread-0 acquired cache lock; Thread-1 waited indefinitely.

    ========================= 1 failed, 1 passed, 1 error in 3.24s =================
""")

initial_state: GraphState = {
    "github_payload": {
        "repository": "acme-corp/flaky-service",
        "repo_path": ".",
        "changed_file": "main.py",
        "test_command": "pytest tests/test_cache.py -v",
        "pr_number": 123,
    },
    "logs": MOCK_LOGS,
    "is_flaky": True,
    "debug_findings": "",        # populated by investigator_agents
    "fix_applied": False,
    "retest_passed": False,
    "document": "",
    "callback_url": "",
}

# ---------------------------------------------------------------------------
# 4. Divider helper
# ---------------------------------------------------------------------------
_SEP = "-" * 72


def _section(title: str) -> None:
    print(f"\n{_SEP}\n  {title}\n{_SEP}")


# ---------------------------------------------------------------------------
# 5. Step 1 -- investigator_agents
# ---------------------------------------------------------------------------
_section("STEP 1 -- investigator_agents  (Bob acts as Alpha + Beta + Gamma)")
print(
    "  Builds one prompt covering all three investigator personas and calls:\n"
    "    bobshell --prompt <prompt>\n"
    "  Bob reads the repo, analyses the diff and logs, and returns findings.\n"
    "  Expected: bobshell responds with structured debug_findings text.\n"
)

try:
    investigator_result = investigator_agents(initial_state)
except Exception as exc:
    investigator_result = {
        "debug_findings": f"[investigator_agents raised an exception]\n{exc}"
    }
    print(f"\n  ERROR: {exc}\n")

debug_findings: str = investigator_result.get("debug_findings", "")

_section("investigator_agents -> debug_findings")
if debug_findings:
    # Print up to 2000 chars so the terminal stays readable.
    preview = debug_findings if len(debug_findings) <= 2000 else debug_findings[:2000] + "\n...(truncated)"
    print(preview)
else:
    print("  (empty -- agents returned no findings)")

# ---------------------------------------------------------------------------
# 6. Step 2 -- fixer_agent
# ---------------------------------------------------------------------------
updated_state: GraphState = {**initial_state, "debug_findings": debug_findings}

_section("STEP 2 -- fixer_agent  (Bob applies the fix via bobshell)")
print(
    "  Builds a fix prompt from debug_findings (is_flaky=True path) and calls:\n"
    "    bobshell --prompt <prompt>\n"
    "  Bob reads the files, applies the minimal fix, and reports back.\n"
    "  Expected: fix_applied=True when bobshell exits with code 0.\n"
    "            fix_applied=False if bobshell is not installed or fails.\n"
)

try:
    fixer_result = fixer_agent(updated_state)
except Exception as exc:
    fixer_result = {"fix_applied": False}
    print(f"\n  ERROR in fixer_agent: {exc}\n")

_section("fixer_agent -> result")
print(f"  fix_applied : {fixer_result.get('fix_applied')}")
print(
    "\n  Interpretation:\n"
    "    True  -- bobshell exited 0; Bob read the context and applied the fix.\n"
    "    False -- bobshell not found, timed out, or exited non-zero.\n"
    "             Install the IBM Bob CLI and ensure it is on PATH.\n"
)

# ---------------------------------------------------------------------------
# 7. Final summary
# ---------------------------------------------------------------------------
_section("SMOKE-TEST COMPLETE")
print(
    f"  is_flaky       : {updated_state['is_flaky']}\n"
    f"  debug_findings : {len(debug_findings)} chars\n"
    f"  fix_applied    : {fixer_result.get('fix_applied')}\n"
    f"\n"
    f"  Next step:\n"
    f"    Ensure 'bobshell' is installed and on PATH, then re-run.\n"
    f"    All intelligence (investigation + fixing + docs) flows through bobshell.\n"
    f"    No API keys or cloud credentials are needed.\n"
)
