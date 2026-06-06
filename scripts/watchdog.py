#!/usr/bin/env python3
"""External uptime watchdog for the Flights Search app.

Runs as a SEPARATE process (systemd timer) so it keeps working when the app
itself is down — an in-process healthcheck cannot email you about its own death.

It pings the app's health URL; on an up->down transition it emails an alert,
and on down->up it emails a recovery notice. State is kept on disk so you get
exactly one email per transition (no spam every tick).

Self-contained: reads .env directly and uses only the stdlib, so a broken app
package never stops the watchdog from running.
"""
from __future__ import annotations

import json
import smtplib
import sys
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
STATE_PATH = ROOT / "logs" / "watchdog_state.json"
LOG_PATH = ROOT / "logs" / "watchdog.log"

# Retries before declaring DOWN — avoids false alarms on a single slow tick.
CHECK_ATTEMPTS = 3
CHECK_TIMEOUT = 8        # seconds per attempt
RETRY_SLEEP = 5          # seconds between attempts


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def log(msg: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    line = f"{stamp} {msg}"
    print(line)
    try:
        with LOG_PATH.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def read_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {"state": "up", "since": None, "fail_count": 0}


def write_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state))
    except OSError as exc:
        log(f"WARN could not write state: {exc}")


def is_up(url: str) -> tuple[bool, str]:
    last_err = ""
    for attempt in range(1, CHECK_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=CHECK_TIMEOUT) as resp:
                if 200 <= resp.status < 400:
                    return True, ""
                last_err = f"HTTP {resp.status}"
        except Exception as exc:  # noqa: BLE001 - any failure = a failed probe
            last_err = f"{type(exc).__name__}: {exc}"
        if attempt < CHECK_ATTEMPTS:
            import time
            time.sleep(RETRY_SLEEP)
    return False, last_err


def send_email(env: dict[str, str], subject: str, body: str) -> bool:
    host = env.get("SMTP_HOST", "")
    to_addr = env.get("WATCHDOG_EMAIL") or env.get("ADMIN_ERROR_EMAILS") or env.get("SMTP_USER", "")
    if not host or not to_addr:
        log(f"WARN cannot email (SMTP_HOST or recipient missing): {subject}")
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = env.get("SMTP_FROM", "flight-watchdog@example.com")
    msg["To"] = to_addr
    try:
        port = int(env.get("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=20) as server:
            if env.get("SMTP_TLS", "true").lower() in ("1", "true", "yes"):
                server.starttls()
            user, pwd = env.get("SMTP_USER", ""), env.get("SMTP_PASSWORD", "")
            if user and pwd:
                server.login(user, pwd)
            server.send_message(msg)
        log(f"EMAIL sent to {to_addr}: {subject}")
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR sending email: {exc}")
        return False


def main() -> int:
    import os
    env = load_env(ENV_PATH)
    env.update({k: v for k, v in os.environ.items() if k in env or k.startswith(("SMTP_", "WATCHDOG_"))})
    url = env.get("WATCHDOG_URL", "http://localhost:8000/")
    prev = read_state()
    now_iso = datetime.now(timezone.utc).isoformat()

    up, err = is_up(url)

    if up:
        if prev.get("state") == "down":
            down_since = prev.get("since") or "unknown"
            send_email(
                env,
                "✅ Flights Search RECOVERED",
                f"App at {url} is back UP.\nWas down since: {down_since}\nRecovered at: {now_iso}",
            )
            log(f"RECOVERED (was down since {down_since})")
        else:
            log("OK app up")
        write_state({"state": "up", "since": now_iso, "fail_count": 0})
        return 0

    # Down
    if prev.get("state") != "down":
        send_email(
            env,
            "🚨 Flights Search is DOWN",
            f"App at {url} failed health check.\nError: {err}\nDetected at: {now_iso}\n"
            f"systemd should auto-restart it; you'll get a RECOVERED email when it returns.",
        )
        log(f"DOWN detected ({err}) — alert sent")
        write_state({"state": "down", "since": now_iso, "fail_count": 1})
    else:
        # Still down — no repeat email, just bump the counter.
        prev["fail_count"] = prev.get("fail_count", 1) + 1
        write_state(prev)
        log(f"STILL DOWN ({err}) — fail_count={prev['fail_count']}, no repeat email")
    return 1


if __name__ == "__main__":
    sys.exit(main())
