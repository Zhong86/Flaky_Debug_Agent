"""
Run the Flaky Debug Agent graph with a dummy payload.
Usage (from backend/):
    python -m graph
"""

from graph.graph import graph

initial_state = {
    "github_payload": {
        "repository": "my-org/my-repo",
        "run_id": "12345",
        "branch": "main",
    },
    "logs": "FAILED tests/test_example.py::test_flaky_feature - AssertionError",
    "is_flaky": False,
    "debug_findings": "",
    "fix_applied": False,
    "retest_passed": False,
    "document": "",
    "callback_url": "https://example.com/callback/12345",
}

if __name__ == "__main__":
    print("=== Flaky Debug Agent — Graph Run ===\n")
    result = graph.invoke(initial_state)
    print("\n=== Final State ===")
    for key, value in result.items():
        print(f"  {key}: {value}")
