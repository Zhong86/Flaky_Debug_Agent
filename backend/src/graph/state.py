from typing import TypedDict


class GraphState(TypedDict):
    github_payload: dict
    logs: str
    rerun_results: list[dict]  # [{"test_id": "...", "attempts": 5, "passed": 3, "failed": 2}]
    is_flaky: bool

    repo_path: str
    debug_findings: str
    document: str
    callback_url: str
    # The GitHub App installation this run's webhook came from (None: JUnit ingest, no App
    # configured, or the App isn't installed there) — clone_repo falls back to GITHUB_TOKEN
    # when it's absent.
    installation_id: int | None
