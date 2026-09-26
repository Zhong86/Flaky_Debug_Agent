"""
Run the Flaky Debug Agent graph with a dummy payload.
Usage (from backend/):
    python -m graph
"""

import asyncio

from graph.graph import graph

initial_state = {
    "github_payload": {
        "repository": "octocat/Hello-World",
        "run_id": "12345",
        "branch": "",
    },
    "logs": "FAILED tests/test_example.py::test_flaky_feature - AssertionError",
    "rerun_results": [
        {"test_id": "tests/test_example.py::test_flaky_feature", "attempts": 5, "passed": 3, "failed": 2}
    ],
    "is_flaky": False,
    "repo_path": "",
    "debug_findings": "",
    "fix_applied": False,
    "retest_passed": False,
    "document": "",
    "callback_url": "https://example.com/callback/12345",
}

if __name__ == "__main__":
    print("=== Flaky Debug Agent — Graph Run ===\n")
    result = asyncio.run(graph.ainvoke(initial_state))
    print("\n=== Final State ===")
    for key, value in result.items():
        print(f"  {key}: {value}")
