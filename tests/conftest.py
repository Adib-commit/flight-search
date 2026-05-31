import os
import sys

import pytest

# Make the project root importable so `import app...` works under pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(autouse=True)
def _force_mock_provider(monkeypatch):
    """Unit tests must never hit a live provider — force the offline mock."""
    monkeypatch.setenv("PROVIDER", "mock")
