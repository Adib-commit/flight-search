# Architecture & Deployment

Flight best-value search engine. Single FastAPI process serving a static
browser frontend, aggregating flight data from three RapidAPI providers,
with a background price-watcher that emails alerts.

## Deployment topology

```mermaid
flowchart TB
    subgraph host["Host (Linux / WSL2) — systemd"]
        svc["flight-search.service<br/>Restart=always · port 8000<br/>logs → logs/server.log"]

        subgraph proc["uvicorn process — app.main:app"]
            api["FastAPI app<br/>/api/* JSON · / HTML · /static/*"]
            sched["APScheduler (AsyncIOScheduler)<br/>price watcher: every 30 min<br/>healthcheck: every 10 min"]
            search["search.py · scoring.py<br/>ValueScore ranking"]
            mp["MultiProvider<br/>asyncio.gather (parallel)"]
        end

        subgraph data["Local files (data/, logs/)"]
            users["users.json<br/>(bcrypt + TOTP/MFA)"]
            watches["watches.json<br/>(per-user watches + price history)"]
            applog["logs/app.log<br/>(SEARCH / PERF traces)"]
        end
    end

    browser["Browser<br/>static/app.js + index.html"]

    subgraph rapidapi["RapidAPI providers (external HTTPS)"]
        kiwi["kiwi-com-cheap-flights<br/>~2s"]
        kayak["kayak-api<br/>~3s"]
        sky["skyscanner-flights-travel-api<br/>~40s cold / ~3s warm"]
    end

    smtp["SMTP server<br/>(price-drop emails)"]

    browser -->|"POST /api/search?tier=fast then tier=full"| api
    browser -->|"JWT bearer (login / MFA)"| api
    api --> search --> mp
    mp -->|fast tier| kiwi & kayak
    mp -->|full tier| kiwi & kayak & sky
    api --> users
    sched --> search
    sched --> watches
    sched -->|price drop| smtp
    smtp -->|alert| enduser["End-user email"]
    proc --> applog
```

## Two-phase search flow

`/api/search` accepts a `tier` query param. The frontend fires both in
sequence so first results paint fast, then get upgraded:

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as FastAPI /api/search
    participant K as Kiwi + Kayak
    participant S as Skyscanner

    B->>A: tier=fast
    A->>K: parallel fetch
    K-->>A: ~50 itineraries (~3s)
    A-->>B: scored payload → render
    Note over B: "Checking Skyscanner…"
    B->>A: tier=full
    A->>K: parallel fetch
    A->>S: parallel fetch (session now warm)
    S-->>A: ~270 itineraries (~3s warm)
    A-->>B: full scored payload → replace
    Note over B: Skyscanner failure ⇒ keep fast results
```

## Components

| Layer | File(s) | Role |
|-------|---------|------|
| Web / API | `app/main.py` | FastAPI routes, auth, validation handler, static mount |
| Search core | `app/search.py`, `app/scoring.py`, `app/filters.py` | fetch → filter → ValueScore → present; `fast` tier flag |
| Providers | `app/providers.py` + `*_client.py` / `*_transform.py` | `MultiProvider` runs Kiwi/Kayak/Skyscanner in parallel via RapidAPI, dedupes, per-provider PERF timing |
| Watcher | `app/watcher.py`, `app/notifier.py` | APScheduler interval jobs; SMTP price-drop alerts |
| Auth | `app/auth.py` | JWT, bcrypt passwords, TOTP MFA |
| Frontend | `static/app.js`, `static/index.html`, `static/airports.js` | search form, results, top-picks, charts, watches UI |
| State | `data/users.json`, `data/watches.json` | flat-file persistence (no DB) |

## Runtime facts

- **Process:** `uvicorn app.main:app --host 0.0.0.0 --port 8000`, managed by
  `systemd` unit `flight-search.service` (`Restart=always`, `RestartSec=3`).
- **Providers:** all three reached over RapidAPI (`*.p.rapidapi.com`) using
  an `x-rapidapi-key`. Pricing is always queried `adults=1` (per-person).
- **Schedules:** price watcher every 30 min, healthcheck every 10 min
  (APScheduler, in-process).
- **Persistence:** flat JSON files under `data/` — no external database.
- **Notifications:** SMTP (skipped silently if `SMTP_HOST` unset).
- **Observability:** structured logs in `logs/app.log` — `SEARCH start/done`,
  per-provider `PERF`, watcher ticks.
