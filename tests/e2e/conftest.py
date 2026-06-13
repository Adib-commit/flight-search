"""conftest for e2e tests — override the root autouse mock-provider fixture.

The root conftest forces PROVIDER=mock for unit tests.  E2E tests hit real
providers, so we undo that override here by redefining the same fixture name
with autouse=True, but without the monkeypatch.
"""
import pytest


@pytest.fixture(autouse=True)
def _force_mock_provider():
    """No-op override: e2e tests must use real providers, not the mock."""
    yield
