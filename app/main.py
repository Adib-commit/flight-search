from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .airlines import UnknownAirlineError
from .amadeus_client import AmadeusError
from .auth import (
    authenticate, change_password, create_mfa_session_token,
    create_token, create_user, create_reset_token, reset_password_with_token,
    decode_token, delete_user, get_user_by_id, get_user_by_email, list_users,
    mfa_begin_enable, mfa_confirm_enable, mfa_disable, mfa_verify_login,
    set_user_role, _users, _save as _save_users,
)
from .config import get_settings
from .logging_config import setup_logging
from .kiwi_client import KiwiError
from .kiwi_rapidapi_client import KiwiRapidError
from .kayak_client import KayakError
from .skyscanner_client import SkyscannerError
from .models import SearchRequest, SearchResponse, StopoverRequest, StopoverResponse
from .rapidapi_client import RapidApiError
from .search import NoResultsError, run_search, run_stopover_search, run_split_suggestion
from .validation import ValidationError
from . import watcher
from .watcher import run_checks_now

STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    log_file = setup_logging(settings.log_level)
    log = logging.getLogger(__name__)
    log.info("App startup: provider=%s currency=%s log=%s",
             settings.provider, settings.currency, log_file)
    watcher.start_scheduler()
    yield
    log.info("App shutdown: stopping price-watcher scheduler")
    watcher.stop_scheduler()


app = FastAPI(title="Flight Optimization App", lifespan=lifespan)


# ── friendly validation errors ─────────────────────────────────────────────────
# Pydantic request-validation failures (e.g. a malformed date) default to a raw
# array payload that the UI cannot render. Convert them to a single clear string.

_FIELD_LABELS = {
    "departure": "Departure date",
    "ret": "Return date",
    "return": "Return date",
    "origin": "Origin",
    "destination": "Destination",
    "traveler_count": "Number of travelers",
    "max_price": "Max price",
    "max_connections": "Max connections",
    "date": "Date",
}


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    parts: list[str] = []
    for err in exc.errors():
        loc = [p for p in err.get("loc", []) if p != "body"]
        field = next((str(p) for p in reversed(loc) if str(p) in _FIELD_LABELS), loc[-1] if loc else "input")
        label = _FIELD_LABELS.get(str(field), str(field))
        msg = err.get("msg", "is invalid")
        bad = err.get("input")
        if "date" in str(field).lower() or label.endswith("date"):
            parts.append(f"{label}: '{bad}' is not a valid date (use YYYY-MM-DD).")
        else:
            parts.append(f"{label}: {msg}.")
    detail = " ".join(parts) or "Invalid request."
    return JSONResponse(status_code=422, content={"detail": detail})


# ── auth helpers ──────────────────────────────────────────────────────────────

def _get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    user = get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return user


def _require_admin(user: dict = Depends(_get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


# ── auth endpoints ────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/register", status_code=201)
async def register(req: RegisterRequest) -> dict[str, Any]:
    try:
        user = create_user(req.username, req.email, req.password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    token = create_token(user["id"], user["username"], user["role"])
    return {"token": token, "user": user}


@app.post("/api/auth/login")
async def login(req: LoginRequest) -> dict[str, Any]:
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    # If MFA is enabled, issue a short-lived session token instead of the full token
    raw = _users.get(user["id"], {})
    if raw.get("mfa_enabled"):
        mfa_session = create_mfa_session_token(user["id"])
        return {"mfa_required": True, "mfa_session": mfa_session}
    token = create_token(user["id"], user["username"], user["role"])
    return {"token": token, "user": user}


class MfaVerifyRequest(BaseModel):
    mfa_session: str
    totp_code: str


@app.post("/api/auth/mfa-verify")
async def mfa_verify(req: MfaVerifyRequest) -> dict[str, Any]:
    payload = decode_token(req.mfa_session)
    if not payload or payload.get("scope") != "mfa_session":
        raise HTTPException(status_code=401, detail="Invalid or expired MFA session.")
    user_id = payload["sub"]
    if not mfa_verify_login(user_id, req.totp_code):
        raise HTTPException(status_code=401, detail="Invalid authenticator code.")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    safe = {k: v for k, v in user.items() if k not in ("hashed_password", "mfa_secret", "mfa_secret_pending")}
    token = create_token(user["id"], user["username"], user["role"])
    return {"token": token, "user": safe}


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@app.post("/api/auth/forgot-password")
async def forgot_password(req: ForgotPasswordRequest, request: Request) -> dict:
    """Send a password-reset link to the given email (always returns 200 to prevent enumeration)."""
    from .notifier import send_password_reset_email
    settings = get_settings()
    token = create_reset_token(req.email)
    if token:
        user = get_user_by_email(req.email)
        base_url = str(request.base_url).rstrip("/")
        reset_url = f"{base_url}/login?reset_token={token}"
        try:
            send_password_reset_email(
                settings,
                to_email=req.email,
                reset_url=reset_url,
                username=user["username"],
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("Reset email failed: %s", e)
    return {"detail": "If that email is registered, a reset link has been sent."}


@app.post("/api/auth/reset-password")
async def reset_password(req: ResetPasswordRequest) -> dict:
    try:
        username = reset_password_with_token(req.token, req.new_password)
        return {"detail": f"Password updated for {username}. You can now sign in."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/change-password")
async def api_change_password(
    req: ChangePasswordRequest,
    user: dict = Depends(_get_current_user),
) -> dict:
    try:
        change_password(user["id"], req.old_password, req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True}


@app.post("/api/auth/mfa/enable")
async def api_mfa_enable(user: dict = Depends(_get_current_user)) -> dict:
    try:
        return mfa_begin_enable(user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class TotpRequest(BaseModel):
    totp_code: str


@app.post("/api/auth/mfa/confirm")
async def api_mfa_confirm(
    req: TotpRequest,
    user: dict = Depends(_get_current_user),
) -> dict:
    try:
        mfa_confirm_enable(user["id"], req.totp_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "mfa_enabled": True}


@app.delete("/api/auth/mfa")
async def api_mfa_disable(
    req: TotpRequest,
    user: dict = Depends(_get_current_user),
) -> dict:
    try:
        mfa_disable(user["id"], req.totp_code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "mfa_enabled": False}


@app.get("/api/auth/me")
async def me(user: dict = Depends(_get_current_user)) -> dict[str, Any]:
    _HIDDEN = {"hashed_password", "mfa_secret", "mfa_secret_pending"}
    return {k: v for k, v in user.items() if k not in _HIDDEN}


# ── search ────────────────────────────────────────────────────────────────────

@app.post("/api/search", response_model=SearchResponse)
async def search(req: SearchRequest, tier: str = "full") -> SearchResponse:
    settings = get_settings()
    try:
        return await run_search(req, settings, fast=(tier == "fast"))
    except (ValidationError, UnknownAirlineError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except NoResultsError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (AmadeusError, KiwiError, RapidApiError, KiwiRapidError, KayakError, SkyscannerError) as e:
        logging.getLogger(__name__).error(
            "Provider error on %s→%s: %s", req.origin, req.destination, e, exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))
    except RuntimeError as e:
        # e.g. all providers failed simultaneously (transient API outage)
        logging.getLogger(__name__).error(
            "All providers failed on %s→%s: %s", req.origin, req.destination, e, exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/search/stopover", response_model=StopoverResponse)
async def search_stopover(req: StopoverRequest) -> StopoverResponse:
    """Multi-day stopover search: run each leg independently and combine."""
    settings = get_settings()
    try:
        return await run_stopover_search(req, settings)
    except NoResultsError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (AmadeusError, KiwiError, RapidApiError, KiwiRapidError, KayakError, SkyscannerError) as e:
        raise HTTPException(status_code=502, detail=str(e))


class SplitSuggestionRequest(BaseModel):
    search: SearchRequest
    via: str   # detected via airport (e.g. "OTP")


@app.post("/api/search/split-suggestion", response_model=StopoverResponse | None)
async def search_split_suggestion(req: SplitSuggestionRequest):
    """Agent-built multi-day split suggestion: called async by frontend after main search."""
    settings = get_settings()
    try:
        result = await run_split_suggestion(req.search, req.via, settings)
        return result
    except Exception:
        return None


# ── watches ───────────────────────────────────────────────────────────────────

class WatchRequest(BaseModel):
    email: str
    search: SearchRequest


@app.post("/api/watches", status_code=201)
async def create_watch(
    req: WatchRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(_get_current_user),
) -> dict[str, Any]:
    settings = get_settings()
    current_best: float | None = None
    current_booking_url = ""
    current_carriers: list[str] = []
    try:
        result = await run_search(req.search, settings)
        if result.cheapest:
            current_best = result.cheapest.price_total
            current_booking_url = result.cheapest.booking_url
            current_carriers = result.cheapest.carrier_names
    except Exception:
        pass

    s = req.search
    watch = watcher.add_watch(
        user_id=user["id"],
        email=req.email,
        origin=s.origin.strip().upper(),
        destination=s.destination.strip().upper(),
        departure=s.flight_dates.departure.isoformat(),
        ret=s.flight_dates.ret.isoformat() if s.flight_dates.ret else None,
        traveler_count=s.traveler_count,
        max_connections=s.max_connections,
        airline_filters=s.airline_filters.model_dump(),
        max_price=s.max_price,
        current_best=current_best,
        current_carriers=current_carriers,
        current_booking_url=current_booking_url,
        currency=settings.currency,
    )

    # Send confirmation email in background (non-blocking)
    from .notifier import send_watch_confirmation
    background_tasks.add_task(
        send_watch_confirmation,
        settings,
        to_email=req.email,
        origin=s.origin.strip().upper(),
        destination=s.destination.strip().upper(),
        departure=s.flight_dates.departure.isoformat(),
        ret=s.flight_dates.ret.isoformat() if s.flight_dates.ret else None,
        current_price=current_best,
        currency=settings.currency,
        booking_url=current_booking_url,
        carriers=current_carriers,
    )
    return {**watch, "current_best": current_best}


@app.get("/api/watches")
async def list_watches_endpoint(
    user: dict = Depends(_get_current_user),
) -> list[dict[str, Any]]:
    # Admins see all watches; regular users see only their own
    uid = None if user.get("role") == "admin" else user["id"]
    return watcher.list_watches(user_id=uid)


@app.post("/api/watches/run-now")
async def watches_run_now(current_user: dict = Depends(_get_current_user)):
    """Immediately trigger a price check for all active watches belonging to this user.
    Admins check all watches."""
    uid = current_user["id"]
    is_admin = current_user.get("role") == "admin"
    summary = await run_checks_now(user_id=None if is_admin else uid)
    return {"checked": len(summary), "results": summary}


@app.get("/api/watches/{watch_id}/history")
async def watch_history(
    watch_id: str,
    user: dict = Depends(_get_current_user),
) -> list[dict[str, Any]]:
    w = watcher.get_watch(watch_id)
    if not w:
        raise HTTPException(status_code=404, detail="Watch not found.")
    if user.get("role") != "admin" and w.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Not your watch.")
    return w.get("price_history", [])


@app.delete("/api/watches/{watch_id}")
async def delete_watch(
    watch_id: str,
    user: dict = Depends(_get_current_user),
) -> dict:
    uid = None if user.get("role") == "admin" else user["id"]
    if not watcher.remove_watch(watch_id, user_id=uid):
        raise HTTPException(status_code=404, detail="Watch not found.")
    return {}


@app.delete("/api/watches/{watch_id}/history")
async def clear_watch_history(
    watch_id: str,
    user: dict = Depends(_get_current_user),
) -> dict:
    """Clear one watch's price history (admin, or the watch's owner)."""
    uid = None if user.get("role") == "admin" else user["id"]
    if not watcher.clear_history(watch_id, user_id=uid):
        raise HTTPException(status_code=404, detail="Watch not found.")
    return {"cleared": watch_id}


@app.delete("/api/admin/watches/history")
async def admin_clear_all_history(_: dict = Depends(_require_admin)) -> dict:
    """Clear price history for ALL watches (admin only)."""
    count = watcher.clear_all_history(user_id=None)
    return {"cleared_watches": count}


@app.post("/api/watches/{watch_id}/test-email")
async def test_watch_email(
    watch_id: str,
    user: dict = Depends(_get_current_user),
) -> dict[str, Any]:
    w = watcher.get_watch(watch_id)
    if not w:
        raise HTTPException(status_code=404, detail="Watch not found.")
    if user.get("role") != "admin" and w.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Not your watch.")
    settings = get_settings()
    from .notifier import send_price_alert
    try:
        price = w.get("best_price") or 0.0
        send_price_alert(
            settings,
            to_email=w["email"],
            origin=w["origin"],
            destination=w["destination"],
            departure=w["departure"],
            ret=w.get("ret"),
            new_price=price,
            old_price=price + 10.0,
            currency=w.get("currency", "USD"),
            booking_url="",
            carriers=["(test notification)"],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email send failed: {e}")
    return {"sent": True, "to": w["email"]}


# ── admin ─────────────────────────────────────────────────────────────────────

@app.get("/api/admin/users")
async def admin_users(_: dict = Depends(_require_admin)) -> list[dict[str, Any]]:
    """Return every user with their watches and price history counts."""
    users = list_users()
    all_watches = watcher.list_watches()  # all
    by_user: dict[str, list] = {}
    for w in all_watches:
        uid = w.get("user_id", "")
        by_user.setdefault(uid, []).append(w)
    for u in users:
        u["watches"] = by_user.get(u["id"], [])
    return users


class AdminCreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"


@app.post("/api/admin/users", status_code=201)
async def admin_create_user(
    req: AdminCreateUserRequest,
    current: dict = Depends(_require_admin),
) -> dict[str, Any]:
    try:
        user = create_user(req.username, req.email, req.password)
        if req.role == "admin":
            set_user_role(user["id"], "admin")
            user["role"] = "admin"
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {k: v for k, v in user.items() if k != "hashed_password"}


@app.delete("/api/admin/users/{user_id}")
async def admin_delete_user(
    user_id: str,
    current: dict = Depends(_require_admin),
) -> dict:
    if user_id == current["id"]:
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")
    # remove user's watches first
    owned = [wid for wid, w in watcher._watches.items() if w.get("user_id") == user_id]
    for wid in owned:
        del watcher._watches[wid]
    if owned:
        watcher._save()
    try:
        if not delete_user(user_id):
            raise HTTPException(status_code=404, detail="User not found.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {}


@app.patch("/api/admin/users/{user_id}/role")
async def admin_set_role(
    user_id: str,
    body: dict,
    _: dict = Depends(_require_admin),
) -> dict[str, Any]:
    role = body.get("role", "user")
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="role must be 'user' or 'admin'")
    if not set_user_role(user_id, role):
        raise HTTPException(status_code=404, detail="User not found.")
    return {"id": user_id, "role": role}


# ── static files ──────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login")
async def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/account")
async def account_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "account.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
