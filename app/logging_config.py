"""Central logging config: timestamped output to console + rotating file.

Call setup_logging() once at startup (FastAPI lifespan / scheduler / scripts).
All module loggers (logging.getLogger(__name__)) inherit this root config, so
every log line gets a timestamp, level, logger name, and source line number.
"""
from __future__ import annotations

import logging
import logging.handlers
import threading
import time
from datetime import datetime
from pathlib import Path

_CONFIGURED = False
_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_FILE = _LOG_DIR / "app.log"

# 2026-05-31 11:42:07 | INFO     | app.search:88 | message...
_FMT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _admin_emails(settings) -> list[str]:
    """Admin recipients = users with role=admin + any configured extras."""
    emails: list[str] = []
    try:
        from .auth import list_users
        emails = [u["email"] for u in list_users()
                  if u.get("role") == "admin" and u.get("email")]
    except Exception:
        pass
    extra = [e.strip() for e in (settings.admin_error_emails or "").split(",") if e.strip()]
    # de-dupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for e in emails + extra:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


class AdminEmailHandler(logging.Handler):
    """Emails admins on ERROR/CRITICAL log records. Throttled + non-blocking.

    - Sends in a daemon thread so logging never blocks on SMTP.
    - Dedupes by logger+func+message for a cooldown window to avoid storms.
    - Skips records from the mail path itself to prevent feedback loops.
    - Swallows all its own exceptions (a broken alerter must not crash the app).
    """

    def __init__(self, cooldown_sec: int = 600):
        super().__init__(level=logging.ERROR)
        self._cooldown = cooldown_sec
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.ERROR:
                return
            if record.name.startswith("app.notifier") or record.name.startswith("smtplib"):
                return
            sig = f"{record.name}:{record.funcName}:{record.getMessage()[:100]}"
            now = time.time()
            with self._lock:
                if now - self._last.get(sig, 0.0) < self._cooldown:
                    return
                self._last[sig] = now
            formatted = self.format(record)
            when = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
            threading.Thread(
                target=self._send, args=(record, formatted, when), daemon=True
            ).start()
        except Exception:
            pass

    def _send(self, record: logging.LogRecord, formatted: str, when: str) -> None:
        try:
            from .config import get_settings
            from .notifier import send_admin_error_alert
            settings = get_settings()
            if not settings.admin_error_alerts or not settings.smtp_host:
                return
            recipients = _admin_emails(settings)
            if not recipients:
                return
            send_admin_error_alert(
                settings,
                to_emails=recipients,
                level=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
                detail=formatted,
                when=when,
            )
        except Exception:
            pass


def _our_handlers_present() -> bool:
    """Return True if our specific RotatingFileHandler (to _LOG_FILE) is attached.

    Uvicorn calls logging.config.dictConfig() on startup, wiping handlers.
    After that, the lifespan re-attaches ours. We check the exact file path
    so multiple processes sharing the same root logger don't double-add.
    """
    log_file_str = str(_LOG_FILE)
    return any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "baseFilename", None) == log_file_str
        for h in logging.getLogger().handlers
    )


def setup_logging(level: int | str = logging.INFO) -> Path:
    """Attach timestamped file + admin-alert handlers to root logger.

    Safe to call multiple times: skips if our RotatingFileHandler is already
    present, re-attaches if uvicorn's dictConfig wiped it.
    """
    global _CONFIGURED

    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # Always ensure root level is set correctly.
    root = logging.getLogger()
    root.setLevel(level)

    if _our_handlers_present():
        return _LOG_FILE   # already wired, nothing to do

    _LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    fileh = logging.handlers.RotatingFileHandler(
        _LOG_FILE, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    fileh.setFormatter(fmt)
    root.addHandler(fileh)   # addHandler so uvicorn's StreamHandler stays too

    # Admin error-alert handler (ERROR+). Best-effort.
    try:
        from .config import get_settings
        s = get_settings()
        if s.admin_error_alerts:
            # Don't add a second AdminEmailHandler if one already exists.
            if not any(isinstance(h, AdminEmailHandler) for h in root.handlers):
                admin_h = AdminEmailHandler(cooldown_sec=s.error_alert_cooldown_min * 60)
                admin_h.setFormatter(fmt)
                root.addHandler(admin_h)
    except Exception:
        pass

    # Tame noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)

    _CONFIGURED = True
    logging.getLogger(__name__).info(
        "Logging configured: level=%s → %s", logging.getLevelName(level), _LOG_FILE
    )
    return _LOG_FILE
