from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Flaky Debug Agent API"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]
    database_url: str = "postgresql://postgres:postgres@localhost:55432/flaky_debug"

    # GitHub App — how we reach the user's CI (dispatch reruns, download artifacts).
    github_app_id: str | None = None
    # PEM contents inline (e.g. for deployments) takes precedence over the file path.
    github_app_private_key: SecretStr | None = None
    github_app_private_key_path: Path | None = None
    github_webhook_secret: SecretStr | None = None
    github_api_url: str = "https://api.github.com"

    # Only failures of these workflow names trigger a flaky rerun; empty = every workflow.
    watched_workflows: list[str] = []
    # Contract with the "Flaky Rerun" workflow living in the user's repo (see README).
    rerun_workflow_file: str = "flaky-rerun.yml"
    rerun_workflow_name: str = "Flaky Rerun"
    rerun_attempts: int = 10
    junit_artifact_prefix: str = "junit"
    max_artifact_bytes: int = 50_000_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
