from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Flaky Debug Agent API"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]
    database_url: str = "postgresql://postgres:postgres@localhost:55432/flaky_debug"

    # Stand-in for a GitHub App installation token until App auth is wired up —
    # a PAT with repo/actions scope on the target repo works the same way here.
    github_token: str = ""
    github_api_base: str = "https://api.github.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
