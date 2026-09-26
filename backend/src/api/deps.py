from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from langgraph.graph.state import CompiledStateGraph

from core.config import Settings, get_settings
from core.security import verify_github_signature
from services.github_app import GitHubApp, load_private_key

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def verified_body(request: Request, settings: SettingsDep) -> bytes:
    """Raw request body, only after its `X-Hub-Signature-256` checks out."""
    if settings.github_webhook_secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GITHUB_WEBHOOK_SECRET is not set")
    body = await request.body()
    secret = settings.github_webhook_secret.get_secret_value()
    if not verify_github_signature(secret, body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")
    return body


VerifiedBody = Annotated[bytes, Depends(verified_body)]


def get_graph(request: Request) -> CompiledStateGraph | None:
    """The checkpointed graph compiled in the app lifespan (None if it never started)."""
    return getattr(request.app.state, "graph", None)


GraphDep = Annotated[CompiledStateGraph | None, Depends(get_graph)]


@lru_cache
def _github_app(app_id: str, private_key: str, api_url: str) -> GitHubApp:
    # One instance per credential set, so installation tokens are cached across requests.
    return GitHubApp(app_id, private_key, api_url)


def get_github_app(settings: SettingsDep) -> GitHubApp | None:
    private_key = load_private_key(settings)
    if not settings.github_app_id or not private_key:
        return None
    return _github_app(settings.github_app_id, private_key, settings.github_api_url)


GitHubAppDep = Annotated[GitHubApp | None, Depends(get_github_app)]
