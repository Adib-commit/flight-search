"""Guard against NameErrors in rarely-hit watcher paths.

The combined-email path (_send_combined) only runs when a real price drop fires,
so a missing import (`send_combined_price_alert` was never imported) slipped past
every test and crashed in production at the first drop. These checks assert every
notifier symbol the watcher calls is actually bound in its namespace.
"""
from __future__ import annotations

import ast
import os

import app.watcher as watcher

_WATCHER_PATH = os.path.join(os.path.dirname(watcher.__file__), "watcher.py")


def test_notifier_symbols_used_are_bound():
    """Every send_* name called in watcher.py must resolve in its module namespace."""
    src = open(_WATCHER_PATH, encoding="utf-8").read()
    tree = ast.parse(src)
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id.startswith("send_")
    }
    assert called, "Expected watcher to call at least one send_* notifier function."
    missing = [name for name in called if not hasattr(watcher, name)]
    assert not missing, f"watcher.py calls undefined notifier symbol(s): {missing}"


def test_combined_alert_is_imported():
    """Explicit regression guard for the exact bug that shipped."""
    assert hasattr(watcher, "send_combined_price_alert")
    assert hasattr(watcher, "send_price_alert")
