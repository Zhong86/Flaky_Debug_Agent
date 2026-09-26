from collections.abc import Iterator

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api.deps import get_graph
from core.config import Settings, get_settings
from main import app
from services import flaky_pipeline, github_client
from services.github_app import GitHubApp
from tests.helpers import GITHUB_TOKEN, WEBHOOK_SECRET, FakeGitHub, FakeGraph


@pytest.fixture(autouse=True)
def settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin every setting the code reads, whatever a developer's backend/.env says."""
    env = {
        "GITHUB_TOKEN": GITHUB_TOKEN,
        "GITHUB_API_BASE": "https://api.github.com",
        "GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET,
        "WATCHED_WORKFLOWS": '["CI"]',
        "RERUN_ATTEMPTS": "5",
        "MAX_ARTIFACT_BYTES": "1000000",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fake_github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHub:
    """Every GitHub API call in every test goes to this fake, never the network."""
    fake = FakeGitHub()
    monkeypatch.setattr(github_client, "transport", httpx.MockTransport(fake.handler))
    return fake


@pytest.fixture
def settings() -> Settings:
    """The live settings object — tweak attributes on it to change behaviour in a test."""
    return get_settings()


@pytest.fixture(scope="session")
def private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def github_app(fake_github: FakeGitHub, private_key_pem: str) -> GitHubApp:
    return GitHubApp(
        "12345", private_key_pem, "https://api.github.com", httpx.MockTransport(fake_github.handler)
    )


@pytest.fixture
def fake_graph() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def client(fake_graph: FakeGraph) -> Iterator[TestClient]:
    app.dependency_overrides[get_graph] = lambda: fake_graph
    flaky_pipeline.claimed.clear()
    # No `with`: the lifespan (which needs Postgres) must not run.
    yield TestClient(app)
    app.dependency_overrides.clear()
