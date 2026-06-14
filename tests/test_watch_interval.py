"""Per-watch interval: due-dispatch logic + interval update guard."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import watcher


@pytest.fixture(autouse=True)
def _isolate_store(monkeypatch):
    """Never touch the real data/watches.json; work on an in-memory dict."""
    monkeypatch.setattr(watcher, "_save", lambda: None)
    monkeypatch.setattr(watcher, "_watches", {})
    yield


def _mk(watch_id="w1", **over):
    w = {
        "id": watch_id, "user_id": "u1", "active": True,
        "interval_minutes": 120, "last_checked": None,
    }
    w.update(over)
    watcher._watches[watch_id] = w
    return w


NOW = datetime(2026, 6, 14, 12, 0, 0)


def test_never_checked_is_due():
    assert watcher._is_due(_mk(last_checked=None), NOW) is True


def test_inactive_never_due():
    assert watcher._is_due(_mk(active=False, last_checked=None), NOW) is False


def test_recent_check_not_due():
    w = _mk(last_checked=(NOW - timedelta(minutes=30)).isoformat())
    assert watcher._is_due(w, NOW) is False


def test_elapsed_interval_is_due():
    w = _mk(last_checked=(NOW - timedelta(minutes=130)).isoformat())
    assert watcher._is_due(w, NOW) is True


def test_slack_lets_near_due_run_on_grid():
    # 110min elapsed, interval 120: within half the 30min dispatch grid → due,
    # so a tick-boundary check isn't pushed out to ~150min.
    w = _mk(last_checked=(NOW - timedelta(minutes=110)).isoformat())
    assert watcher._is_due(w, NOW) is True


def test_custom_interval_respected():
    w = _mk(interval_minutes=1440, last_checked=(NOW - timedelta(minutes=130)).isoformat())
    assert watcher._is_due(w, NOW) is False  # 24h watch, only 130min passed


def test_bad_timestamp_is_due():
    assert watcher._is_due(_mk(last_checked="not-a-date"), NOW) is True


def test_update_interval_valid():
    _mk()
    assert watcher.update_watch_interval("w1", 240, user_id="u1") is True
    assert watcher._watches["w1"]["interval_minutes"] == 240


def test_update_interval_rejects_unsupported_value():
    _mk()
    assert watcher.update_watch_interval("w1", 45, user_id="u1") is False
    assert watcher._watches["w1"]["interval_minutes"] == 120


def test_update_interval_rejects_non_owner():
    _mk()
    assert watcher.update_watch_interval("w1", 240, user_id="someone-else") is False


def test_update_interval_admin_bypasses_owner():
    _mk()
    assert watcher.update_watch_interval("w1", 360, user_id=None) is True
