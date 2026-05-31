"""User authentication: bcrypt passwords, JWT tokens, JSON-file user store."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pyotp
from jose import JWTError, jwt
from passlib.context import CryptContext

# ── config ────────────────────────────────────────────────────────────────────

SECRET_KEY = "flight-opt-secret-change-in-prod-32bytes!!"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 h

_pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
_DATA_DIR = Path(__file__).parent.parent / "data"
_DATA_DIR.mkdir(exist_ok=True)
_STORE = _DATA_DIR / "users.json"

# In-memory: user_id -> user dict
_users: dict[str, dict[str, Any]] = {}


# ── persistence ───────────────────────────────────────────────────────────────

def _load() -> None:
    if _STORE.exists():
        try:
            _users.update(json.loads(_STORE.read_text()))
        except Exception:
            pass


def _save() -> None:
    _STORE.write_text(json.dumps(_users, indent=2, default=str))


_load()

# Create default admin on first run
if not any(u.get("role") == "admin" for u in _users.values()):
    import os as _os
    _admin_email = _os.getenv("SMTP_FROM") or "admin@local"
    _aid = str(uuid.uuid4())[:8]
    _users[_aid] = {
        "id": _aid,
        "username": "admin",
        "email": _admin_email,
        "hashed_password": _pwd.hash("admin123"),
        "role": "admin",
        "created_at": datetime.now().isoformat(),
    }
    _save()


# ── public helpers ────────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


def get_user_by_username(username: str) -> dict | None:
    for u in _users.values():
        if u["username"].lower() == username.lower():
            return u
    return None


def get_user_by_email(email: str) -> dict | None:
    for u in _users.values():
        if u["email"].lower() == email.lower():
            return u
    return None


def get_user_by_id(user_id: str) -> dict | None:
    return _users.get(user_id)


def list_users() -> list[dict]:
    return [
        {k: v for k, v in u.items() if k != "hashed_password"}
        for u in _users.values()
    ]


def delete_user(user_id: str) -> bool:
    if user_id not in _users:
        return False
    if _users[user_id].get("role") == "admin":
        admins = [u for u in _users.values() if u.get("role") == "admin"]
        if len(admins) <= 1:
            raise ValueError("Cannot delete the last admin account.")
    del _users[user_id]
    _save()
    return True


def set_user_role(user_id: str, role: str) -> bool:
    if user_id not in _users:
        return False
    _users[user_id]["role"] = role
    _save()
    return True


def create_user(username: str, email: str, password: str) -> dict:
    if get_user_by_username(username):
        raise ValueError(f"Username '{username}' is already taken.")
    if get_user_by_email(email):
        raise ValueError(f"Email '{email}' is already registered.")
    uid = str(uuid.uuid4())[:8]
    user = {
        "id": uid,
        "username": username,
        "email": email,
        "hashed_password": hash_password(password),
        "role": "user",
        "created_at": datetime.now().isoformat(),
    }
    _users[uid] = user
    _save()
    return {k: v for k, v in user.items() if k != "hashed_password"}


def authenticate(username: str, password: str) -> dict | None:
    user = get_user_by_username(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return {k: v for k, v in user.items() if k != "hashed_password"}


def change_password(user_id: str, old_password: str, new_password: str) -> None:
    user = _users.get(user_id)
    if not user:
        raise ValueError("User not found.")
    if not verify_password(old_password, user["hashed_password"]):
        raise ValueError("Current password is incorrect.")
    if len(new_password) < 8:
        raise ValueError("New password must be at least 8 characters.")
    _users[user_id]["hashed_password"] = hash_password(new_password)
    _save()


# ── MFA (TOTP) ────────────────────────────────────────────────────────────────

MFA_ISSUER = "FlightOpt"


def mfa_begin_enable(user_id: str) -> dict:
    """Generate a new TOTP secret and store it as pending (not yet active).
    Returns {secret, otpauth_uri} for the client to render a QR code."""
    user = _users.get(user_id)
    if not user:
        raise ValueError("User not found.")
    secret = pyotp.random_base32()
    _users[user_id]["mfa_secret_pending"] = secret
    _save()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=user["username"], issuer_name=MFA_ISSUER
    )
    return {"secret": secret, "otpauth_uri": uri}


def mfa_confirm_enable(user_id: str, totp_code: str) -> None:
    """Verify the first TOTP code and activate MFA."""
    user = _users.get(user_id)
    if not user:
        raise ValueError("User not found.")
    secret = user.get("mfa_secret_pending")
    if not secret:
        raise ValueError("No pending MFA setup. Call enable first.")
    if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
        raise ValueError("Invalid TOTP code.")
    _users[user_id]["mfa_secret"] = secret
    _users[user_id]["mfa_enabled"] = True
    _users[user_id].pop("mfa_secret_pending", None)
    _save()


def mfa_disable(user_id: str, totp_code: str) -> None:
    """Disable MFA after verifying current TOTP code."""
    user = _users.get(user_id)
    if not user:
        raise ValueError("User not found.")
    secret = user.get("mfa_secret")
    if not secret or not user.get("mfa_enabled"):
        raise ValueError("MFA is not enabled.")
    if not pyotp.TOTP(secret).verify(totp_code, valid_window=1):
        raise ValueError("Invalid TOTP code.")
    _users[user_id]["mfa_enabled"] = False
    _users[user_id].pop("mfa_secret", None)
    _save()


def mfa_verify_login(user_id: str, totp_code: str) -> bool:
    """Return True if the TOTP code is valid for this user."""
    user = _users.get(user_id)
    if not user or not user.get("mfa_enabled"):
        return False
    secret = user.get("mfa_secret", "")
    return pyotp.TOTP(secret).verify(totp_code, valid_window=1)


def create_token(user_id: str, username: str, role: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user_id, "username": username, "role": role, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def create_mfa_session_token(user_id: str) -> str:
    """Short-lived token issued after password check when MFA is required."""
    expire = datetime.utcnow() + timedelta(minutes=5)
    return jwt.encode(
        {"sub": user_id, "scope": "mfa_session", "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── password reset ─────────────────────────────────────────────────────────────

RESET_TOKEN_EXPIRE_MINUTES = 30


def create_reset_token(email: str) -> str | None:
    """Issue a 30-minute signed reset token for the given email.
    Returns None if no account with that email exists."""
    user = get_user_by_email(email)
    if not user:
        return None
    expire = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": user["id"], "scope": "password_reset", "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def reset_password_with_token(token: str, new_password: str) -> str:
    """Validate the reset token and set the new password.
    Returns the username on success, raises ValueError on bad token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise ValueError("Reset link is invalid or has expired.")
    if payload.get("scope") != "password_reset":
        raise ValueError("Invalid token scope.")
    user_id = payload.get("sub")
    if not user_id or user_id not in _users:
        raise ValueError("User not found.")
    if len(new_password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    _users[user_id]["hashed_password"] = hash_password(new_password)
    _save()
    return _users[user_id]["username"]
