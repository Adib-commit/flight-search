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
from .notifier import send_price_alert
from .search import NoResultsError, run_search

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_DATA_DIR.mkdir(exist_ok=True)
_STORE_PATH = _DATA_DIR / "watches.json"
_watches: dict[str, dict[str, Any]] = {}
scheduler = AsyncIOScheduler()


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
    old_best = watch.get("best_price")  # None = no real baseline yet

    watch["last_checked"] = now
    watch["last_price"] = new_price
    entry: dict = {
        "checked_at": now, "price": new_price,
        "carriers": carriers, "booking_url": booking_url, "note": "check",
    }
    watch.setdefault("price_history", []).append(entry)
    logger.info("WATCH %s result new_price=%s best=%s carriers=%s",
                watch["id"], new_price, old_best, ",".join(carriers) or "-")

    if new_price is None:
        logger.warning("WATCH %s no price this check", watch["id"])
        _save()
        return

    if old_best is None:
        # First real result — record as baseline, no email
        watch["best_price"] = new_price
        entry["note"] = "first-check baseline"
        logger.info("Watch %s: first baseline %.2f", watch["id"], new_price)
    elif new_price < old_best:
        entry["note"] = f"DROP from {old_best:.2f}"
        watch["best_price"] = new_price
        logger.info("Watch %s: DROP %.2f → %.2f, emailing %s",
                    watch["id"], old_best, new_price, watch["email"])
        try:
            send_price_alert(
                settings,
                to_email=watch["email"],
                origin=watch["origin"],
                destination=watch["destination"],
                departure=watch["departure"],
                ret=watch.get("ret"),
                new_price=new_price,
                old_price=old_best,
                currency=watch["currency"],
                booking_url=booking_url,
                carriers=carriers,
            )
        except Exception as e:
            logger.error("Watch %s: price-drop email to %s failed: %s",
                         watch["id"], watch["email"], e, exc_info=True)
    elif new_price > old_best:
        entry["note"] = f"rose from best {old_best:.2f}"
        logger.info("Watch %s: price rose %.2f → %.2f (best stays %.2f)",
                    watch["id"], old_best, new_price, old_best)
    else:
        entry["note"] = "unchanged"

    _save()


async def _healthcheck() -> None:
    active = sum(1 for w in _watches.values() if w.get("active"))
    logger.info("HEALTHCHECK ok: app running, scheduler alive, %d active watch(es)", active)


async def _run_all_watches() -> None:
    t0 = datetime.now()
    active = [w for w in _watches.values() if w.get("active")]
    logger.info("WATCHER tick: checking %d active watch(es)", len(active))
    await asyncio.gather(*[_check_watch(w) for w in active])
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
    scheduler.add_job(_run_all_watches, "interval", minutes=30, id="price_watcher",
                      next_run_time=datetime.now() + timedelta(seconds=60))
    scheduler.add_job(_healthcheck, "interval", minutes=10, id="healthcheck",
                      next_run_time=datetime.now())
    scheduler.start()
    logger.info("Price watcher scheduler started (watch=30min, healthcheck=10min).")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
