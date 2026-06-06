# Deployment (systemd)

Copy the units to `/etc/systemd/system/`, then reload + enable:

```bash
sudo cp deploy/flights-search.service   /etc/systemd/system/
sudo cp deploy/flights-watchdog.service /etc/systemd/system/
sudo cp deploy/flights-watchdog.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flights-search.service
sudo systemctl enable --now flights-watchdog.timer
```

## flights-search.service
Runs the app under uvicorn on :8000 with `Restart=always` (auto-restart on crash).

## flights-watchdog.timer + .service
Runs `scripts/watchdog.py` every 2 min as a **separate process**. It pings
`WATCHDOG_URL` and emails `WATCHDOG_EMAIL` on an up→down transition and again on
recovery — exactly one email per transition (state in `logs/watchdog_state.json`).

External on purpose: an in-process healthcheck cannot alert you when the app
itself is dead. Requires `SMTP_*` + `WATCHDOG_EMAIL` set in `.env`.

Check:
```bash
systemctl list-timers flights-watchdog.timer
tail -f logs/watchdog.log
```
