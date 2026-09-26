from typing import TypedDict


class GraphState(TypedDict):
    github_payload: dict
    logs: str
    rerun_results: list[dict]  # [{"test_id": "...", "attempts": 5, "passed": 3, "failed": 2}]
    is_flaky: bool

    repo_path: str
    debug_findings: str
    fix_applied: bool
    fix_branch: str
    fix_sha: str
    retest_passed: bool
    document: str
    callback_url: str
