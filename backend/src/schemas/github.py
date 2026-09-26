"""The subset of GitHub webhook payloads the endpoints read, plus our own responses.

Everything ignores unknown keys — GitHub payloads are large and grow over time.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _GitHubModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RepositoryRef(_GitHubModel):
    full_name: str
    default_branch: str = "main"


class PullRequestRef(_GitHubModel):
    number: int


class Installation(_GitHubModel):
    id: int


class WorkflowRun(_GitHubModel):
    id: int
    name: str
    display_title: str = ""
    head_branch: str | None = None
    head_sha: str
    status: str | None = None
    conclusion: str | None = None
    run_attempt: int = 1
    html_url: str = ""
    event: str = ""
    pull_requests: list[PullRequestRef] = []
    head_repository: RepositoryRef | None = None


class WorkflowRunEvent(_GitHubModel):
    action: str
    workflow_run: WorkflowRun
    repository: RepositoryRef
    installation: Installation | None = None


class WebhookAck(BaseModel):
    received: bool = True
    action: Literal["rerun_scheduled", "analysis_scheduled", "ignored"]
    reason: str | None = None
    thread_id: str | None = None


class JUnitIngest(BaseModel):
    """Manual ingest: JUnit XML reports grouped by attempt number (0 = the original CI run)."""

    repository: str = Field(pattern=r"^[\w.-]+/[\w.-]+$", examples=["octocat/Hello-World"])
    run_id: str = Field(min_length=1, description="Becomes the dashboard thread_id.")
    branch: str = ""
    sha: str = ""
    run_url: str = ""
    reports: dict[int, list[str]] = Field(min_length=1)
