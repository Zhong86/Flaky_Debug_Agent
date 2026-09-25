from typing import TypedDict


class GraphState(TypedDict):
    github_payload: dict
    logs: str
    is_flaky: bool
    debug_findings: str
    fix_applied: bool
    retest_passed: bool
    document: str
    callback_url: str
