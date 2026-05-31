# Flight Optimization App — Workplan

## Stack (live)
Python 3.12 · FastAPI + Uvicorn · Pydantic v2 · httpx async · APScheduler · tenacity · passlib/python-jose/pyotp

## Providers
`PROVIDER=multi` → Kiwi.com Cheap Flights + Kayak + Skyscanner in parallel via single RapidAPI key.
One-way legs use `sector` key; round-trip uses `outbound`/`inbound`.

## Scoring (live — `app/scoring.py`)
    ValueScore = Ws·connections_per_dir(absolute) + Wp·norm_price + Wd·norm_duration + Wl·norm_layover

| Weight | Value | Notes |
|--------|-------|-------|
| `weight_stops`    | 0.30 | Absolute per-direction connection count (not normalised) |
| `weight_duration` | 0.30 | Min-max normalised total travel time |
| `weight_price`    | 0.25 | Min-max normalised price |
| `weight_layover`  | 0.15 | Min-max normalised total layover |

`prune_unreasonable()` drops outliers before scoring:
total_time ≤ max(fastest×2.5, fastest+360min); layover ≤ 600min; keeps ≥5 shortest if pruning leaves <4.

## Layout
```
flights_search/
  app/
    config.py              # settings + weights + log_level + admin alert config
    models.py              # SearchRequest, Itinerary, SearchResponse, Stopover*, ScoreBreakdown
    validation.py          # IATA, future dates, dep<ret
    providers.py           # Provider protocol + MultiProvider (parallel, retry, dedup)
    kiwi_rapidapi_client.py / _transform.py   # primary — real LCC fares
    kayak_client.py / kayak_transform.py
    skyscanner_client.py / skyscanner_transform.py
    filters.py             # max_connections, include/exclude, max_price, prune_unreasonable
    scoring.py             # ValueScore engine + score_breakdown
    output.py              # build_response, to_out, build_markdown
    search.py              # run_search, run_stopover_search, run_split_suggestion
    watcher.py             # per-user watches, APScheduler (watch=30min, healthcheck=10min)
    notifier.py            # SMTP: price_alert, watch_confirmation, admin_error_alert, pw_reset
    logging_config.py      # setup_logging: console + RotatingFile + AdminEmailHandler
    auth.py                # JWT, MFA/TOTP, password reset
    main.py                # FastAPI routes: search, stopover, split-suggestion, watches, admin, auth
    airlines.py            # name→IATA map
  static/                  # index.html, login.html, admin.html, account.html, app.js, style.css
  logs/
    app.log                # timestamped app log (5MB×5 rotating)
    server.log             # uvicorn process log (timestamped)
    uvicorn_log_config.json
  data/
    users.json             # hashed passwords, roles, MFA secrets
    watches.json           # active price watchers + price history
  docs/
    WORKPLAN.md
    flight_agent_instructions.md
  scripts/
    verify_scrapers.py
    check_price_drop.py
  tests/
  .env / .env.example
  CLAUDE.md                # project requirements (auto-loaded by Claude Code)
  requirements.txt
```

## Features (done ✓ / pending ✗)

| # | Requirement | Status |
|---|-------------|--------|
| 1 | Search: origin, dest, dates, travelers, connection/direct, include/exclude airlines | ✓ |
| 2 | Best-value score = low cost + min stops + min layover | ✓ |
| 3 | Cost per flight bar chart | ✓ |
| 4 | Full route list, selected highlighted, times in hours | ✓ |
| 5 | Max-price filter | ✓ |
| 6 | Booking URL per result | ✓ |
| 7 | Airport name (not only IATA) | ✓ |
| 8 | Number-of-connections filter | ✓ |
| 9 | Batch mode: 30min checks, email on price drop, email param | ✓ |
| 10 | Multi-day stopover section (legs on different days) | ✓ |
| 11 | Multi-scrapers: Kiwi + Kayak + Skyscanner | ✓ |
| 12 | Auto-detect split connections in main search | ✓ |
| 13 | Multiple watchers + stopover-leg watchers | ✓ (watches generic; stopover watch = separate legs) |
| 14 | Detailed timestamped logging (app.log + server.log) | ✓ |
| 15 | Healthcheck every 10min to logs | ✓ |
| 16 | Admin error email on ERROR/CRITICAL | ✓ |

## Backlog (P1 — build next)

| # | Item | Why |
|---|------|-----|
| B1 | `GET /api/health` endpoint | Monitoring; WORKPLAN P2 item 8 |
| B2 | `max_stops_per_dir` in kayak/skyscanner/rapidapi transforms | Currently -1; per-direction filter inaccurate for those providers |
| B3 | Sort toggle for stopover legs | Currently cheapest-first; expose best_value/fastest in UI |
| B4 | ±1 day window search for stopover legs | Find cheaper combos near requested date |

## Backlog (P2 — nice-to-have)

| # | Item |
|---|------|
| B5 | Score breakdown "Why this score?" collapsible in UI |
| B6 | Short-lived result cache (5min TTL) to avoid duplicate API calls |
| B7 | Weight tuning sliders in admin UI |

## Run
```bash
# start
fuser -k 8000/tcp
nohup .venv/bin/python3 -m uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 --workers 1 --no-access-log \
  --log-config logs/uvicorn_log_config.json \
  > logs/server.log 2>&1 &

# logs
tail -f logs/app.log    # app events (search, watcher, healthcheck, errors)
tail -f logs/server.log # uvicorn process events

# manual watcher check
.venv/bin/python3 -c "import asyncio, app.watcher as w; print(asyncio.run(w.run_checks_now()))"
```

## Key Config (.env)
```
PROVIDER=multi
RAPIDAPI_KEY=<key>
KIWI_RAPIDAPI_HOST=kiwi-com-cheap-flights.p.rapidapi.com
KAYAK_RAPIDAPI_HOST=kayak-api.p.rapidapi.com
SKYSCANNER_RAPIDAPI_HOST=skyscanner-flights-travel-api.p.rapidapi.com
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<email>
SMTP_PASSWORD=<app-password>
SMTP_FROM=<email>
LOG_LEVEL=INFO
ADMIN_ERROR_ALERTS=true
ERROR_ALERT_COOLDOWN_MIN=10
```
