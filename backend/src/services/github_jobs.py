"""Job/step status and logs for a workflow run — the demo page's `gh run watch` view.

Separate from github_dispatch.py (which owns the flaky-rerun.yml dispatch contract):
these are raw, workflow-agnostic Actions API calls used by api/routes/demo.py.
"""

from services.github_client import github_client


async def list_run_jobs(repo: str, run_id: int, installation_id: int | None = None) -> list[dict]:
    """A demo run has one or two jobs, so a single page is always enough."""
    async with await github_client(installation_id) as client:
        resp = await client.get(f"/repos/{repo}/actions/runs/{run_id}/jobs", params={"per_page": 100})
        resp.raise_for_status()
        return resp.json()["jobs"]


async def get_job_logs(repo: str, job_id: int, installation_id: int | None = None) -> str:
    """Plain-text log captured so far, even while the job is still running.

    GitHub 404s until a runner has actually picked the job up (still queued) —
    that's not a failure, just nothing to show yet.
    """
    async with await github_client(installation_id) as client:
        resp = await client.get(f"/repos/{repo}/actions/jobs/{job_id}/logs")
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        return resp.text
