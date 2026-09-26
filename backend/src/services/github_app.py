"""GitHub App auth: app JWT → per-installation access token → authenticated API client.

The App is how we reach a user's CI: it's installed on their repo, every webhook
carries its `installation.id`, and an installation token (valid 1h) lets us dispatch
workflows and download artifacts there. Tokens stay in memory only — never put them
in graph state, which is checkpointed to Postgres and shown on the dashboard.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime

import httpx
import jwt

from core.config import Settings

API_VERSION = "2022-11-28"
# Refresh a cached installation token when it has less than this many seconds left.
_REFRESH_MARGIN_SECONDS = 300


def load_private_key(settings: Settings) -> str | None:
    if settings.github_app_private_key is not None:
        return settings.github_app_private_key.get_secret_value()
    if settings.github_app_private_key_path is not None:
        return settings.github_app_private_key_path.read_text()
    return None


@dataclass
class _CachedToken:
    token: str
    expires_at: float  # unix timestamp


class GitHubApp:
    def __init__(
        self,
        app_id: str,
        private_key: str,
        api_url: str = "https://api.github.com",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.app_id = app_id
        self._private_key = private_key
        self._api_url = api_url
        self._transport = transport
        self._tokens: dict[int, _CachedToken] = {}
        self._lock = asyncio.Lock()

    def app_jwt(self, now: float | None = None) -> str:
        """Short-lived JWT identifying the App itself (GitHub caps `exp` at 10 minutes)."""
        issued_at = int(time.time() if now is None else now)
        claims = {"iat": issued_at - 60, "exp": issued_at + 540, "iss": self.app_id}
        return jwt.encode(claims, self._private_key, algorithm="RS256")

    async def installation_token(self, installation_id: int) -> str:
        async with self._lock:
            cached = self._tokens.get(installation_id)
            if cached and cached.expires_at - time.time() > _REFRESH_MARGIN_SECONDS:
                return cached.token

            async with self._client(self.app_jwt()) as client:
                response = await client.post(f"/app/installations/{installation_id}/access_tokens")
                response.raise_for_status()
            data = response.json()
            expires_at = datetime.fromisoformat(data["expires_at"]).timestamp()
            self._tokens[installation_id] = _CachedToken(data["token"], expires_at)
            return data["token"]

    async def installation_client(self, installation_id: int) -> httpx.AsyncClient:
        """API client acting as the App inside one installation. Use as `async with`."""
        return self._client(await self.installation_token(installation_id))

    def _client(self, bearer: str) -> httpx.AsyncClient:
        # Artifact downloads redirect to blob storage; httpx drops the Authorization
        # header when a redirect leaves the API host, so following them is safe.
        return httpx.AsyncClient(
            base_url=self._api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {bearer}",
                "X-GitHub-Api-Version": API_VERSION,
            },
            timeout=httpx.Timeout(10.0, read=60.0),
            follow_redirects=True,
            transport=self._transport,
        )
