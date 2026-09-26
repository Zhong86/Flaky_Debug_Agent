"""services/github_app.py — GitHub App auth, kept for when it replaces the PAT."""

import time

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from services.github_app import GitHubApp
from tests.helpers import INSTALLATION_TOKEN, FakeGitHub


def test_app_jwt_is_rs256_signed_with_github_claims(
    github_app: GitHubApp, private_key_pem: str
) -> None:
    now = time.time()
    public_key = load_pem_private_key(private_key_pem.encode(), None).public_key()

    claims = jwt.decode(github_app.app_jwt(now), public_key, algorithms=["RS256"])

    assert claims["iss"] == "12345"
    assert claims["iat"] == int(now) - 60  # backdated for clock drift
    assert claims["exp"] - claims["iat"] == 600  # GitHub's 10 minute maximum


async def test_installation_token_is_cached(github_app: GitHubApp, fake_github: FakeGitHub) -> None:
    assert await github_app.installation_token(99) == INSTALLATION_TOKEN
    assert await github_app.installation_token(99) == INSTALLATION_TOKEN

    [token_request] = fake_github.calls("POST", r"/app/installations/99/access_tokens")
    assert token_request.headers["Authorization"].startswith("Bearer ey")  # the app JWT


async def test_installation_token_near_expiry_is_refreshed(
    github_app: GitHubApp, fake_github: FakeGitHub
) -> None:
    fake_github.token_expires_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)
    )

    await github_app.installation_token(99)
    await github_app.installation_token(99)

    assert len(fake_github.calls("POST", r"/app/installations/99/access_tokens")) == 2


async def test_installation_client_authenticates_as_the_installation(
    github_app: GitHubApp, fake_github: FakeGitHub
) -> None:
    async with await github_app.installation_client(99) as client:
        await client.get("/repos/acme/shop/actions/runs/1")

    [request] = fake_github.calls("GET", r"/repos/acme/shop/actions/runs/1")
    assert request.headers["Authorization"] == f"Bearer {INSTALLATION_TOKEN}"
