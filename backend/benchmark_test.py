"""
benchmark_test.py -- Single-shot latency benchmark for the bobshell pipeline.

Run from the `backend/` directory:

    python benchmark_test.py

Runs each agent node EXACTLY ONCE (no loops, no retries) and prints the
wall-clock time spent shelling out to bobshell for each step.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap -- make graph.* importable from backend/src/
# ---------------------------------------------------------------------------
_BACKEND_SRC = Path(__file__).parent / "src"
if str(_BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(_BACKEND_SRC))

from graph.agents import documenter_agent, fixer_agent, investigator_agents  # noqa: E402
from graph.state import GraphState  # noqa: E402

# ---------------------------------------------------------------------------
# Mock state -- simulated TOCTOU flaky-test failure, no real repo needed
# ---------------------------------------------------------------------------
MOCK_CI_LOGS = (
    "FAILED tests/test_cache.py::test_concurrent_write - "
    "TimeoutError: lock acquisition timed out after 5.00s\n"
    "Thread-0 acquired cache lock; Thread-1 waited indefinitely.\n"
    "Intermittent: passed 7/10 runs, failed 3/10 runs (TOCTOU race condition)."
)

state: GraphState = {
    "github_payload": {
        "repo_path": ".",
        "changed_file": "src/cache.py",
        "test_command": "pytest tests/test_cache.py -v",
    },
    "logs": MOCK_CI_LOGS,
    "is_flaky": True,
    "debug_findings": "",
    "fix_applied": False,
    "retest_passed": False,
    "document": "",
    "callback_url": "",
}

SEP = "-" * 68


def _hdr(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")


# ---------------------------------------------------------------------------
# Step 1 -- investigator_agents (ONCE)
# ---------------------------------------------------------------------------
_hdr("STEP 1 -- investigator_agents")

t0 = time.time()
inv_result = investigator_agents(state)
t1 = time.time()

state = {**state, **inv_result}

print(f"\n  latency      : {t1 - t0:.2f}s")
print(f"  debug_findings: {len(state['debug_findings'])} chars")

# ---------------------------------------------------------------------------
# Step 2 -- fixer_agent (ONCE)
# ---------------------------------------------------------------------------
_hdr("STEP 2 -- fixer_agent")

t2 = time.time()
fix_result = fixer_agent(state)
t3 = time.time()

state = {**state, **fix_result}

print(f"\n  latency   : {t3 - t2:.2f}s")
print(f"  fix_applied: {state['fix_applied']}")

# ---------------------------------------------------------------------------
# Step 3 -- documenter_agent (ONCE)
# ---------------------------------------------------------------------------
_hdr("STEP 3 -- documenter_agent")

t4 = time.time()
doc_result = documenter_agent(state)
t5 = time.time()

state = {**state, **doc_result}

print(f"\n  latency : {t5 - t4:.2f}s")
print(f"  document: {state['document'] or '(none)'}")

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total = t5 - t0
_hdr("BENCHMARK COMPLETE")
print(
    f"  investigator_agents : {t1 - t0:6.2f}s\n"
    f"  fixer_agent         : {t3 - t2:6.2f}s\n"
    f"  documenter_agent    : {t5 - t4:6.2f}s\n"
    f"  {SEP[:40]}\n"
    f"  total pipeline      : {total:6.2f}s\n"
    f"\n"
    f"  fix_applied : {state['fix_applied']}\n"
    f"  document    : {state['document'] or '(none)'}\n"
)
