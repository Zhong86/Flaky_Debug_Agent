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

    # Fallback auth when no GitHub App is configured below (or a call has no
    # installation, e.g. the JUnit ingest endpoint): a PAT with repo/actions scope.
    github_token: str = ""
    github_api_base: str = "https://api.github.com"

    # Shared secret of the repo webhook; every request to /api/webhooks/* must be
    # signed with it (X-Hub-Signature-256).
    github_webhook_secret: SecretStr | None = None
    # Only failures of these workflow names trigger a flaky rerun; empty = every workflow.
    watched_workflows: list[str] = []
    # Parallel attempts per flaky-rerun.yml dispatch.
    rerun_attempts: int = 5
    # Cap on JUnit XML pulled from one run's artifacts.
    max_artifact_bytes: int = 50_000_000

    # GitHub App credentials (services/github_app.py). When set, every webhook's
    # installation.id gets its own installation token instead of the PAT above.
    github_app_id: str | None = None
    github_app_private_key: SecretStr | None = None
    github_app_private_key_path: Path | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
