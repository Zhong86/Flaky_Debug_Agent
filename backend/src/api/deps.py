from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from langgraph.graph.state import CompiledStateGraph

from core.config import Settings, get_settings
from core.security import verify_github_signature

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def verified_body(request: Request, settings: SettingsDep) -> bytes:
    """Raw request body, only after its `X-Hub-Signature-256` checks out."""
    secret = settings.github_webhook_secret
    if secret is None or not secret.get_secret_value():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GITHUB_WEBHOOK_SECRET is not set")
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_github_signature(secret.get_secret_value(), body, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook signature")
    return body


VerifiedBody = Annotated[bytes, Depends(verified_body)]


def get_graph(request: Request) -> CompiledStateGraph | None:
    """The checkpointed graph compiled in the app lifespan (None if it never started)."""
    return getattr(request.app.state, "graph", None)


GraphDep = Annotated[CompiledStateGraph | None, Depends(get_graph)]
