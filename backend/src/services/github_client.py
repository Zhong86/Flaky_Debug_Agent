"""The one place that builds authenticated GitHub API clients.

Prefers a GitHub App installation token when the App is configured (services/github_app.py)
and the caller has an `installation_id` — every webhook carries one. Falls back to the PAT
in GITHUB_TOKEN otherwise: no App configured, or a caller with no installation (the JUnit
ingest endpoint, local dev).
"""

import httpx

from core.config import get_settings
from services.github_app import get_github_app

API_VERSION = "2022-11-28"

# Tests swap in an httpx.MockTransport here so no test ever reaches the real API.
transport: httpx.AsyncBaseTransport | None = None


async def _resolve_token(installation_id: int | None) -> str | None:
    if installation_id is not None and (app := get_github_app()) is not None:
        return await app.installation_token(installation_id)
    return get_settings().github_token or None


async def github_client(installation_id: int | None = None, timeout: float = 30.0) -> httpx.AsyncClient:
    """Async client for the GitHub REST API. Use as `async with await github_client() as client`."""
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
    if token := await _resolve_token(installation_id):
        headers["Authorization"] = f"Bearer {token}"
    # Artifact downloads redirect to blob storage; httpx drops the Authorization
    # header when a redirect leaves the API host, so following them is safe.
    return httpx.AsyncClient(
        base_url=settings.github_api_base,
        headers=headers,
        timeout=httpx.Timeout(timeout, read=60.0),
        follow_redirects=True,
        transport=transport,
    )
