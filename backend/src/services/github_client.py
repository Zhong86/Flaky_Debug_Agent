"""The one place that builds authenticated GitHub API clients.

Auth is the PAT in GITHUB_TOKEN for now; switching to GitHub App installation
tokens (services/github_app.py) only needs to change this module.
"""

import httpx

from core.config import get_settings

API_VERSION = "2022-11-28"

# Tests swap in an httpx.MockTransport here so no test ever reaches the real API.
transport: httpx.AsyncBaseTransport | None = None


def github_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Async client for the GitHub REST API. Use as `async with github_client() as client`."""
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    # Artifact downloads redirect to blob storage; httpx drops the Authorization
    # header when a redirect leaves the API host, so following them is safe.
    return httpx.AsyncClient(
        base_url=settings.github_api_base,
        headers=headers,
        timeout=httpx.Timeout(timeout, read=60.0),
        follow_redirects=True,
        transport=transport,
    )
