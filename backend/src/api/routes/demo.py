"""Judge-facing demo: dispatch a workflow by hand and watch it run, without GitHub.

POST /dispatch kicks off `settings.demo_workflow_file` (default deploy.yml) on
`settings.demo_repo`; the other endpoints are polled by the dashboard to render a
`gh run watch`-style job/step tree plus two log panels (GitHub Actions + this
backend's own activity).
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, status

from api.deps import LogBufferDep, SettingsDep
from core.config import Settings
from services import github_dispatch, github_jobs
from services.github_app import get_github_app

router = APIRouter(prefix="/demo", tags=["demo"])

# Named under "services" (not "api.routes.demo") so services/log_buffer.py's handler,
# attached to logging.getLogger("services"), actually captures these lines.
logger = logging.getLogger("services.demo")


def _require_demo_repo(settings: Settings) -> str:
    if not settings.demo_repo:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DEMO_REPO is not configured")
    return settings.demo_repo


async def _demo_auth(settings: Settings) -> tuple[str, int | None]:
    """The demo repo plus the installation to act as, or None to fall back to GITHUB_TOKEN.

    Nothing hands this path an installation_id the way a webhook delivery does, so when the
    App is configured we resolve it from the repo — otherwise github_client silently drops to
    the PAT, which usually lacks the `workflow` scope and 403s on dispatch.
    """
    repo = _require_demo_repo(settings)
    app = get_github_app()
    if app is None:
        return repo, None
    installation_id = await app.installation_id_for_repo(repo)
    if installation_id is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The GitHub App is not installed on {repo} — install it there, or unset "
            "GITHUB_APP_ID to use GITHUB_TOKEN (needs the `workflow` scope).",
        )
    return repo, installation_id


@router.get("/config")
async def get_demo_config(settings: SettingsDep) -> dict:
    """What the demo is pointed at, so the dashboard can link to it without hardcoding the repo.

    Unlike the other endpoints this one stays 200 when DEMO_REPO is unset — the dashboard uses
    `configured` to decide whether to render the repo link at all.
    """
    repo = settings.demo_repo
    return {
        "configured": bool(repo),
        "repo": repo,
        "workflow_file": settings.demo_workflow_file,
        "ref": settings.demo_ref,
        "repo_url": f"https://github.com/{repo}" if repo else None,
        "actions_url": f"https://github.com/{repo}/actions" if repo else None,
    }


@router.post("/dispatch")
async def dispatch_demo_run(settings: SettingsDep) -> dict:
    """Dispatch and locate the run. Takes a few seconds: dispatch itself returns no run ID."""
    repo, installation_id = await _demo_auth(settings)
    logger.info("Dispatching %s on %s@%s", settings.demo_workflow_file, repo, settings.demo_ref)
    try:
        dispatched_at = await github_dispatch.dispatch_workflow(
            repo, settings.demo_workflow_file, settings.demo_ref, inputs={}, installation_id=installation_id
        )
        run_id = await github_dispatch.find_dispatched_run(
            repo, settings.demo_workflow_file, dispatched_at, installation_id=installation_id
        )
    except TimeoutError as exc:
        logger.error("Dispatch of %s on %s never appeared: %s", settings.demo_workflow_file, repo, exc)
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc

    run = await github_dispatch.get_run(repo, run_id, installation_id)
    logger.info("Run %s dispatched: %s", run_id, run["html_url"])
    return {"run_id": run_id, "html_url": run["html_url"], "status": run["status"]}


@router.get("/runs/{run_id}")
async def get_demo_run(run_id: int, settings: SettingsDep) -> dict:
    """Run status plus its jobs/steps — the tree the dashboard polls and renders."""
    repo, installation_id = await _demo_auth(settings)
    run, jobs = await asyncio.gather(
        github_dispatch.get_run(repo, run_id, installation_id),
        github_jobs.list_run_jobs(repo, run_id, installation_id),
    )
    return {
        "run_id": run_id,
        "status": run["status"],
        "conclusion": run["conclusion"],
        "html_url": run["html_url"],
        "jobs": [
            {
                "id": job["id"],
                "name": job["name"],
                "status": job["status"],
                "conclusion": job["conclusion"],
                "started_at": job.get("started_at"),
                "completed_at": job.get("completed_at"),
                "steps": [
                    {
                        "name": step["name"],
                        "number": step["number"],
                        "status": step["status"],
                        "conclusion": step["conclusion"],
                    }
                    for step in job.get("steps", [])
                ],
            }
            for job in jobs
        ],
    }


@router.get("/jobs/{job_id}/logs")
async def get_demo_job_logs(job_id: int, settings: SettingsDep) -> dict:
    """JSON envelope (not plain text) so "job hasn't started" is a normal 200, not an error."""
    repo, installation_id = await _demo_auth(settings)
    logs = await github_jobs.get_job_logs(repo, job_id, installation_id)
    return {"available": bool(logs), "logs": logs}


@router.get("/backend-logs")
async def get_backend_logs(log_buffer: LogBufferDep, limit: int = 200) -> dict:
    """Recent lines from this backend's own activity — proof the agent is alive and reacting."""
    return {"entries": log_buffer.snapshot(limit)}
