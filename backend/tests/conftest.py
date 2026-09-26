from collections.abc import Iterator

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api.deps import get_github_app, get_graph
from core.config import Settings, get_settings
from main import app
from services import flaky_pipeline
from services.github_app import GitHubApp
from tests.helpers import WEBHOOK_SECRET, FakeGitHub, FakeGraph


@pytest.fixture(scope="session")
def private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def fake_github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def github_app(fake_github: FakeGitHub, private_key_pem: str) -> GitHubApp:
    return GitHubApp(
        "12345", private_key_pem, "https://api.github.com", httpx.MockTransport(fake_github.handler)
    )


@pytest.fixture
def fake_graph() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, github_webhook_secret=WEBHOOK_SECRET, watched_workflows=["CI"])


@pytest.fixture
def client(
    settings: Settings, fake_graph: FakeGraph, github_app: GitHubApp
) -> Iterator[TestClient]:
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_graph] = lambda: fake_graph
    app.dependency_overrides[get_github_app] = lambda: github_app
    flaky_pipeline.dispatched_runs.clear()
    # No `with`: the lifespan (which needs Postgres) must not run.
    yield TestClient(app)
    app.dependency_overrides.clear()
