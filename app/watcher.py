"""Price watcher: per-user watches, price history, correct drop detection."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import get_settings
from .models import AirlineFilters, FlightDates, SearchRequest
from .notifier import send_combined_price_alert, send_price_alert
from .search import NoResultsError, run_search, run_split_suggestion

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_DATA_DIR.mkdir(exist_ok=True)
_STORE_PATH = _DATA_DIR / "watches.json"
_watches: dict[str, dict[str, Any]] = {}
scheduler = AsyncIOScheduler()

# User-tunable per-watch check cadence. The dispatcher wakes every
# _DISPATCH_EVERY_MIN and runs only the watches that are due by their own
# interval, so each user picks how often their watch is checked.
_DEFAULT_INTERVAL_MIN = 120
_ALLOWED_INTERVALS = (60, 120, 240, 360, 720, 1440)  # 1h, 2h, 4h, 6h, 12h, 24h
_DISPATCH_EVERY_MIN = 30

# Only one split search runs at a time across all watches.
# Without this, 4 concurrent watches each fire 90 provider calls = 360 total,
# hitting Kiwi/Kayak rate limits and returning 0 for every split leg.
_SPLIT_SEM = asyncio.Semaphore(1)


# ── persistence ───────────────────────────────────────────────────────────────

def _load() -> None:
    if _STORE_PATH.exists():
        try:
            _watches.update(json.loads(_STORE_PATH.read_text()))
        except Exception:
            pass


def _save() -> None:
    try:
        _STORE_PATH.write_text(json.dumps(_watches, indent=2, default=str))
    except Exception as e:
        logger.warning("Could not save watches: %s", e)


# ── public API ────────────────────────────────────────────────────────────────

def add_watch(
    *,
    user_id: str,
    email: str,
    origin: str,
    destination: str,
    departure: str,
    ret: str | None,
    traveler_count: int,
    max_connections: int | None,
    airline_filters: dict,
    max_price: float | None,
    current_best: float | None = None,
    current_carriers: list[str] | None = None,
    current_booking_url: str = "",
    currency: str = "USD",
) -> dict:
    watch_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    history: list[dict] = []
    if current_best is not None:
        history.append({
            "checked_at": now,
            "price": current_best,
            "carriers": current_carriers or [],
            "booking_url": current_booking_url,
            "note": "baseline",
        })
    watch = {
        "id": watch_id,
        "user_id": user_id,
        "email": email,
        "origin": origin,
        "destination": destination,
        "departure": departure,
        "ret": ret,
        "traveler_count": traveler_count,
        "max_connections": max_connections,
        "airline_filters": airline_filters,
        "max_price": max_price,
        "currency": currency,
        "interval_minutes": _DEFAULT_INTERVAL_MIN,  # user-tunable check cadence
        "best_price": current_best,   # all-time lowest ever seen
        "last_price": current_best,   # most recently observed price
        "created_at": now,
        "last_checked": now if current_best is not None else None,
        "active": True,
        "price_history": history,
    }
    _watches[watch_id] = watch
    _save()
    return watch


def remove_watch(watch_id: str, user_id: str | None = None) -> bool:
    w = _watches.get(watch_id)
    if not w:
        return False
    if user_id is not None and w.get("user_id") != user_id:
        return False
    del _watches[watch_id]
    _save()
    return True


def clear_history(watch_id: str, user_id: str | None = None) -> bool:
    """Empty a watch's price_history and re-baseline its price tracking so the
    next check starts fresh (no stale 'previous best' to compare against)."""
    w = _watches.get(watch_id)
    if not w:
        return False
    if user_id is not None and w.get("user_id") != user_id:
        return False
    w["price_history"] = []
    w["best_price"] = None
    w["last_price"] = None
    w["best_split_price"] = None
    w["last_split_price"] = None
    _save()
    return True


def clear_all_history(user_id: str | None = None) -> int:
    """Clear history for all watches (or all of one user's). Returns count cleared."""
    n = 0
    for w in _watches.values():
        if user_id is not None and w.get("user_id") != user_id:
            continue
        w["price_history"] = []
        w["best_price"] = None
        w["last_price"] = None
        w["best_split_price"] = None
        w["last_split_price"] = None
        n += 1
    if n:
        _save()
    return n


def update_watch_interval(watch_id: str, interval_minutes: int, user_id: str | None = None) -> bool:
    """Set a watch's check cadence. Owner-or-admin (user_id=None bypasses the
    owner check for admins). Rejects values outside _ALLOWED_INTERVALS."""
    if interval_minutes not in _ALLOWED_INTERVALS:
        return False
    w = _watches.get(watch_id)
    if not w:
        return False
    if user_id is not None and w.get("user_id") != user_id:
        return False
    w["interval_minutes"] = interval_minutes
    _save()
    return True


def list_watches(user_id: str | None = None) -> list[dict]:
    if user_id is None:
        return list(_watches.values())
    return [w for w in _watches.values() if w.get("user_id") == user_id]


def get_watch(watch_id: str) -> dict | None:
    return _watches.get(watch_id)


# ── scheduler job ─────────────────────────────────────────────────────────────

async def _check_watch(watch: dict) -> None:
    settings = get_settings()
    now = datetime.now().isoformat()
    logger.info("WATCH %s check start %s→%s dep=%s ret=%s pax=%s best=%s email=%s",
                watch["id"], watch["origin"], watch["destination"],
                watch["departure"], watch.get("ret"), watch["traveler_count"],
                watch.get("best_price"), watch["email"])
    try:
        req = SearchRequest(
            origin=watch["origin"],
            destination=watch["destination"],
            flight_dates=FlightDates(
                departure=watch["departure"],
                **{"return": watch["ret"]} if watch["ret"] else {},
            ),
            traveler_count=watch["traveler_count"],
            max_connections=watch["max_connections"],
            airline_filters=AirlineFilters(**watch["airline_filters"]),
            max_price=watch["max_price"],
        )
        result = await run_search(req, settings)
    except NoResultsError:
        logger.warning("Watch %s: no results", watch["id"])
        watch["last_checked"] = now
        watch.setdefault("price_history", []).append({
            "checked_at": now, "price": None, "carriers": [],
            "booking_url": "", "note": "no results",
        })
        _save()
        return
    except Exception as e:
        err_short = str(e)[:120]
        # A whole-tick provider exhaustion (every provider rate-limited this hour)
        # is transient and self-recovers on the next tick — log it as a WARNING so
        # it does NOT page the admin via the ERROR email handler. Reserve ERROR
        # (which emails) for unexpected exceptions that signal a real bug.
        transient = isinstance(e, RuntimeError) and "provider(s) failed" in str(e)
        if transient:
            logger.warning("Watch %s check failed (transient, will retry next tick): %s",
                           watch["id"], err_short)
        else:
            logger.error("Watch %s check failed: %s", watch["id"], err_short, exc_info=True)
        watch["last_checked"] = now
        watch.setdefault("price_history", []).append({
            "checked_at": now, "price": None, "carriers": [],
            "booking_url": "", "note": f"error: {err_short}",
        })
        _save()
        return

    cheapest = result.cheapest
    new_price: float | None = cheapest.price_total if cheapest else None
    booking_url: str = cheapest.booking_url if cheapest else ""
    carriers: list[str] = cheapest.carrier_names if cheapest else []

    # Evaluate the multi-day split-ticket via the detected hub (e.g. OTP) and
    # track it SEPARATELY from the regular round-trip, so a drop in the split
    # itself alerts even when the regular fare is unchanged (or cheaper).
    split_price: float | None = None
    split_booking_url = ""
    split_carriers: list[str] = []
    split_via_used: str | None = None
    split_note = ""
    try:
        via = getattr(result, "split_via", None) or "OTP"
        if True:  # always attempt split; via defaults to OTP if not detected
            await asyncio.sleep(8)  # brief cooldown so Kiwi/Kayak rate-limits recover
            async with _SPLIT_SEM:  # serialize split searches — one at a time
                split = await run_split_suggestion(req, via, settings)
            if split and split.legs:
                leg_carriers = [
                    (L.options[0].carriers[0] if L.options and L.options[0].carriers else "?")
                    for L in split.legs
                ]
                split_via_used = via
                split_price = split.total_price
                split_booking_url = (split.legs[0].options[0].booking_url
                                     if split.legs[0].options else "")
                split_carriers = [f"split via {via}: " + "/".join(leg_carriers)]
                split_note = f" [multi-day split via {via}: {split_price:.2f}]"
    except Exception as e:
        logger.warning("Watch %s: split check failed: %s", watch["id"], e)

    old_best = watch.get("best_price")        # regular round-trip baseline
    old_split = watch.get("best_split_price")  # multi-day split baseline

    watch["last_checked"] = now
    watch["last_price"] = new_price
    watch["last_split_price"] = split_price
    entry: dict = {
        "checked_at": now, "price": new_price, "split_price": split_price,
        "carriers": carriers, "booking_url": booking_url, "note": "check" + split_note,
    }
    watch.setdefault("price_history", []).append(entry)
    logger.info("WATCH %s result regular=%s split=%s best=%s best_split=%s",
                watch["id"], new_price, split_price, old_best, old_split)

    notes: list[str] = []
    regular_dropped = False
    split_dropped    = False

    # ── regular round-trip drop tracking ────────────────────────────────────
    if new_price is not None:
        if old_best is None:
            watch["best_price"] = new_price
            notes.append("regular first-check baseline")
        elif new_price < old_best:
            watch["best_price"] = new_price
            regular_dropped = True
            notes.append(f"regular DROP from {old_best:.2f}")
            logger.info("Watch %s: regular DROP %.2f → %.2f, emailing %s",
                        watch["id"], old_best, new_price, watch["email"])
        elif new_price > old_best:
            notes.append(f"regular rose from best {old_best:.2f}")
        else:
            notes.append("regular unchanged")

    # ── multi-day split-ticket drop tracking (independent) ──────────────────
    if split_price is not None:
        if old_split is None:
            watch["best_split_price"] = split_price
            notes.append(f"split baseline {split_price:.2f}")
        elif split_price < old_split:
            watch["best_split_price"] = split_price
            split_dropped = True
            notes.append(f"split DROP from {old_split:.2f}")
            logger.info("Watch %s: SPLIT DROP %.2f → %.2f via %s, emailing %s",
                        watch["id"], old_split, split_price, split_via_used, watch["email"])
        elif split_price > old_split:
            notes.append(f"split rose from best {old_split:.2f}")
        else:
            notes.append("split unchanged")

    # ── send ONE combined email when either price dropped ────────────────────
    if regular_dropped or split_dropped:
        _send_combined(settings, watch,
                       new_price, old_best, booking_url, carriers,
                       split_price, old_split, split_booking_url,
                       split_carriers, split_via_used)

    if new_price is None and split_price is None:
        logger.warning("WATCH %s no price this check", watch["id"])

    entry["note"] = "; ".join(notes) if notes else "check" + split_note
    _save()


def _send_combined(settings, watch,
                   regular_price, regular_old, regular_url, regular_carriers,
                   split_price, split_old, split_url, split_carriers, split_via) -> None:
    """Send ONE combined email showing both the regular and split prices."""
    try:
        send_combined_price_alert(
            settings,
            to_email=watch["email"],
            origin=watch["origin"],
            destination=watch["destination"],
            departure=watch["departure"],
            ret=watch.get("ret"),
            currency=watch["currency"],
            regular_price=regular_price,
            regular_old_price=regular_old,
            regular_url=regular_url,
            regular_carriers=regular_carriers,
            split_price=split_price,
            split_old_price=split_old,
            split_url=split_url,
            split_carriers=split_carriers,
            split_via=split_via,
        )
    except Exception as e:
        logger.error("Watch %s: combined email to %s failed: %s",
                     watch["id"], watch["email"], e, exc_info=True)


def _send_drop(settings, watch, new_price, old_price, booking_url, carriers) -> None:
    """Legacy single-option drop email (kept for confirmation emails)."""
    try:
        send_price_alert(
            settings,
            to_email=watch["email"],
            origin=watch["origin"],
            destination=watch["destination"],
            departure=watch["departure"],
            ret=watch.get("ret"),
            new_price=new_price,
            old_price=old_price,
            currency=watch["currency"],
            booking_url=booking_url,
            carriers=carriers,
        )
    except Exception as e:
        logger.error("Watch %s: price-drop email to %s failed: %s",
                     watch["id"], watch["email"], e, exc_info=True)


async def _healthcheck() -> None:
    active = sum(1 for w in _watches.values() if w.get("active"))
    logger.info("HEALTHCHECK ok: app running, scheduler alive, %d active watch(es)", active)


def _is_due(w: dict, now: datetime) -> bool:
    """A watch is due when it has never been checked, or its own interval has
    elapsed since the last check. Per-watch interval defaults to 2h."""
    if not w.get("active"):
        return False
    last = w.get("last_checked")
    if not last:
        return True
    interval = w.get("interval_minutes", _DEFAULT_INTERVAL_MIN)
    try:
        elapsed = (now - datetime.fromisoformat(last)).total_seconds() / 60.0
    except (ValueError, TypeError):
        return True  # unparseable timestamp → check it now rather than stall forever
    # Small slack so a watch due at ~120min isn't skipped to ~150min by the
    # 30min dispatch grid (e.g. last check landed 119min ago on a tick boundary).
    return elapsed >= interval - (_DISPATCH_EVERY_MIN / 2.0)


async def _run_all_watches() -> None:
    """Dispatcher: runs only the watches that are due by their own interval."""
    t0 = datetime.now()
    due = [w for w in _watches.values() if _is_due(w, t0)]
    active = sum(1 for w in _watches.values() if w.get("active"))
    logger.info("WATCHER tick: %d/%d active watch(es) due", len(due), active)
    if not due:
        return
    await asyncio.gather(*[_check_watch(w) for w in due])
    logger.info("WATCHER tick done in %.2fs", (datetime.now() - t0).total_seconds())


async def run_checks_now(user_id: str | None = None) -> list[dict]:
    """Trigger an immediate check for all active watches (or just one user's).
    Returns a summary list of {id, route, old_best, new_price, dropped}."""
    from .logging_config import setup_logging
    setup_logging(get_settings().log_level)
    _load()  # pick up any on-disk changes
    watches = [w for w in _watches.values() if w.get("active")]
    if user_id:
        watches = [w for w in watches if w.get("user_id") == user_id]
    if not watches:
        return []
    # Snapshot best_prices before checks
    before = {w["id"]: w.get("best_price") for w in watches}
    await asyncio.gather(*[_check_watch(w) for w in watches])
    summary = []
    for w in watches:
        old = before[w["id"]]
        new = w.get("last_price")
        summary.append({
            "id": w["id"],
            "route": f"{w['origin']} → {w['destination']}",
            "email": w["email"],
            "old_best": old,
            "new_price": new,
            "dropped": new is not None and old is not None and new < old,
        })
    return summary


def start_scheduler() -> None:
    from .logging_config import setup_logging
    setup_logging(get_settings().log_level)
    _load()
    logger.info("Price watcher: loaded %d watch(es) from %s", len(_watches), _STORE_PATH)
    scheduler.add_job(_run_all_watches, "interval", minutes=_DISPATCH_EVERY_MIN, id="price_watcher",
                      next_run_time=datetime.now() + timedelta(seconds=60))
    scheduler.add_job(_healthcheck, "interval", minutes=10, id="healthcheck",
                      next_run_time=datetime.now())
    scheduler.start()
    logger.info("Price watcher scheduler started (dispatch=%dmin, default interval=%dmin, healthcheck=10min).",
                _DISPATCH_EVERY_MIN, _DEFAULT_INTERVAL_MIN)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
