from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import date, datetime, timedelta

from .airlines import resolve_codes
from .config import Settings
from .filters import apply_filters, prune_unreasonable
from .models import (
    Itinerary,
    SearchRequest, SearchResponse,
    StopoverLegRequest, StopoverLegResult, StopoverRequest, StopoverResponse,
)
from .output import build_response, to_out
from .providers import get_provider, KayakProvider, KiwiRapidProvider, MultiProvider, SkyscannerProvider, WizzProvider
from .scoring import score_itineraries
from .validation import validate_request


logger = logging.getLogger(__name__)


class NoResultsError(RuntimeError):
    pass


def _apply_pax_pricing(itineraries: list[Itinerary], pax: int) -> None:
    """ALL prices are per-person. traveler_count is NOT used to scale price — it
    only gates availability: providers are queried with adults=N, so the returned
    fares are guaranteed bookable for N travelers. Here we just mirror the
    per-person fare into price_per_person; price_total stays per-person."""
    for it in itineraries:
        it.price_per_person = round(it.price_total, 2)


# Minimum gap between a leg's arrival and the next leg's departure. Split legs
# are SEPARATE tickets changing planes at the hub, so a real buffer is needed —
# but the hard rule is simply that a leg may never depart BEFORE the prior leg
# lands (the bug this guards: an overnight leg 1 arriving next morning paired
# with a cheap early leg 2 the same morning).
_SPLIT_MIN_CONNECT_MIN = 60


def _parse_dt(s: str) -> datetime | None:
    """Parse a segment ISO datetime; return naive local time (tz dropped so legs
    from different providers compare on what the traveler actually sees)."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _opt_depart(opt) -> datetime | None:
    return _parse_dt(opt.segments[0].departure_at) if opt.segments else None


def _opt_arrive(opt) -> datetime | None:
    return _parse_dt(opt.segments[-1].arrival_at) if opt.segments else None


def _chronological_plan(
    legs: list[StopoverLegResult], min_connect_min: int = _SPLIT_MIN_CONNECT_MIN,
) -> tuple[float, list[int]] | None:
    """Pick one option per leg forming the CHEAPEST chronologically valid chain:
    each leg's chosen flight must depart >= the prior leg's arrival + buffer.

    Returns (total_price, chosen_option_index_per_leg) or None if no chain fits
    (e.g. every leg-2 option departs before leg 1 can land). Pure: does not
    mutate the legs. DP over <=~3 options x <=4 legs, so brute-cheap.

    When a time can't be parsed for either side of a pair, the pair is allowed —
    we never fabricate an infeasibility we can't prove."""
    opts = [leg.options for leg in legs]
    if any(not o for o in opts):
        return None
    buffer = timedelta(minutes=min_connect_min)
    n = len(legs)
    INF = float("inf")
    dp = [[INF] * len(o) for o in opts]
    nxt = [[-1] * len(o) for o in opts]
    for j, o in enumerate(opts[n - 1]):
        dp[n - 1][j] = o.price_total
    for i in range(n - 2, -1, -1):
        for j, oj in enumerate(opts[i]):
            arr = _opt_arrive(oj)
            best, bk = INF, -1
            for k, ok in enumerate(opts[i + 1]):
                dep = _opt_depart(ok)
                if arr is not None and dep is not None and dep < arr + buffer:
                    continue  # leg i+1 would depart before leg i lands (+buffer)
                if dp[i + 1][k] < best:
                    best, bk = dp[i + 1][k], k
            if bk != -1:
                dp[i][j] = oj.price_total + best
                nxt[i][j] = bk
    start = min(range(len(opts[0])), key=lambda j: dp[0][j])
    if dp[0][start] == INF:
        return None
    chosen = [0] * n
    j = start
    for i in range(n):
        chosen[i] = j
        if i < n - 1:
            j = nxt[i][j]
    return round(dp[0][start], 2), chosen


def _reorder_to_plan(legs: list[StopoverLegResult], chosen: list[int]) -> list[StopoverLegResult]:
    """Copy each leg with its chosen option moved to options[0] (the headline)
    and cheapest_price updated to match. Copies so shared legs aren't mutated."""
    out: list[StopoverLegResult] = []
    for leg, c in zip(legs, chosen):
        lc = leg.model_copy(deep=True)
        if c != 0:
            lc.options.insert(0, lc.options.pop(c))
        lc.cheapest_price = lc.options[0].price_total
        out.append(lc)
    return out


async def run_search(req: SearchRequest, settings: Settings, fast: bool = False) -> SearchResponse:
    """End-to-end: validate -> fetch (provider) -> filter -> score -> present.

    fast=True drops the slow Skyscanner provider so the first page of results
    returns in ~3s; the caller re-queries with fast=False to fold it in.
    """
    t0 = datetime.now()
    validate_request(req)

    include_codes = resolve_codes(req.airline_filters.include)
    exclude_codes = resolve_codes(req.airline_filters.exclude)

    provider = get_provider(settings, fast=fast)

    dep_s = req.flight_dates.departure.isoformat()
    ret_s = req.flight_dates.ret.isoformat() if req.flight_dates.ret else None
    logger.info(
        "SEARCH start %s→%s dep=%s ret=%s pax=%d max_conn=%s max_price=%s incl=%s excl=%s provider=%s",
        req.origin.strip().upper(), req.destination.strip().upper(), dep_s, ret_s,
        req.traveler_count, req.max_connections, req.max_price,
        include_codes or "-", exclude_codes or "-", settings.provider,
    )

    itineraries = await provider.search(
        origin=req.origin.strip().upper(),
        destination=req.destination.strip().upper(),
        departure_date=dep_s,
        return_date=ret_s,
        adults=1,                # ALL pricing is per-person; providers disagree on
                                 # group-price semantics (Kiwi returns 0 for pax>1,
                                 # Skyscanner returns a pax-total) so we always query
                                 # 1 adult. traveler_count is used only downstream.
        non_stop=False,          # always fetch all; connection count filtered locally
        included_airlines=include_codes or None,
        excluded_airlines=exclude_codes or None,
        currency=settings.currency,
    )
    logger.info("SEARCH provider returned %d itineraries in %.2fs",
                len(itineraries), (datetime.now() - t0).total_seconds())

    _apply_pax_pricing(itineraries, req.traveler_count)

    if not itineraries:
        logger.warning("SEARCH no results %s→%s dep=%s",
                       req.origin.strip().upper(), req.destination.strip().upper(), dep_s)
        raise NoResultsError(
            "No flights returned for this route/date. Try different dates or "
            "loosen filters."
        )

    filtered = apply_filters(
        itineraries,
        max_connections=req.max_connections,
        include_codes=include_codes,
        exclude_codes=exclude_codes,
        max_price=req.max_price,
        traveler_count=req.traveler_count,
    )
    logger.info("SEARCH filters kept %d/%d", len(filtered), len(itineraries))

    if not filtered:
        logger.warning("SEARCH all %d filtered out (max_conn=%s max_price=%s)",
                       len(itineraries), req.max_connections, req.max_price)
        n = len(itineraries)
        parts: list[str] = [f"All {n} result{'s' if n != 1 else ''} were removed by your filters."]

        cheapest = min(itineraries, key=lambda it: it.price_total)
        cheapest_pp = cheapest.price_total  # all prices are per-person
        min_stops = min(it.max_stops_per_dir for it in itineraries)
        out_segs = [s for s in cheapest.segments if s.direction in ("outbound", "")]
        cheapest_route = (
            " → ".join(dict.fromkeys(s.origin for s in out_segs))
            + (" → " + out_segs[-1].destination if out_segs else "")
        ) or "unknown route"

        if req.max_price is not None:
            parts.append(
                f"Max price: you set ${req.max_price:.0f}/person but the "
                f"cheapest option costs ${cheapest_pp:.0f}/person "
                f"({'/'.join(cheapest.carriers)} on {cheapest_route})."
            )

        if req.max_connections is not None and min_stops > req.max_connections:
            parts.append(
                f"Max connections: you set {req.max_connections} stop(s)/direction but "
                f"the least-connected itinerary has {min_stops} stop(s)/direction."
            )

        if include_codes:
            matched_airlines = {s.carrier_code for it in itineraries for s in it.segments}
            missing = set(include_codes) - matched_airlines
            if missing:
                parts.append(
                    f"Included airlines: {', '.join(sorted(missing))} not found on this route. "
                    f"Available carriers: {', '.join(sorted(matched_airlines))}."
                )

        if exclude_codes:
            all_carriers = {s.carrier_code for it in itineraries for s in it.segments}
            overlap = set(exclude_codes) & all_carriers
            if overlap and len(overlap) == len(all_carriers):
                parts.append(
                    f"Excluded airlines: all available carriers ({', '.join(sorted(all_carriers))}) "
                    f"are in your exclusion list."
                )

        if len(parts) == 1:
            parts.append(
                f"Cheapest available: ${cheapest_pp:.0f}/person; "
                f"min connections/direction: {min_stops}. "
                f"Try loosening your filters."
            )

        # Don't 404: a multi-day split via the hub (e.g. OTP) may still beat the
        # budget even when every regular itinerary is over it. Return an empty
        # 200 response that carries the explanation + detected via airport so the
        # frontend can render the notice AND still fetch the split suggestion.
        return SearchResponse(
            best_value=[], cheapest=None, fastest=None, options=[],
            total_considered=len(itineraries), markdown="",
            split_via=_find_via_airport(itineraries),
            notice=" ".join(parts),
        )

    sane = prune_unreasonable(filtered)
    logger.info("SEARCH prune kept %d/%d (dropped outliers)", len(sane), len(filtered))
    scored = score_itineraries(sane, settings)
    response = build_response(scored)
    # Tell the frontend which via airport was detected so it can fetch split suggestion
    response.split_via = _find_via_airport(itineraries)

    if scored:
        bv = scored[0]
        cheapest = min(scored, key=lambda it: it.price_total)
        fastest = min(scored, key=lambda it: it.total_duration_min)

        def _route(it: Itinerary) -> str:
            segs = [s for s in it.segments if s.direction in ("outbound", "")] or it.segments
            pts = list(dict.fromkeys(s.origin for s in segs)) + ([segs[-1].destination] if segs else [])
            return "→".join(pts) or "?"

        logger.info(
            "SEARCH done in %.2fs | considered=%d | BEST %.2f %s [%s] %s stops=%d dur=%dmin lay=%dmin score=%s | "
            "CHEAPEST %.2f [%s] %s stops=%d dur=%dmin url=%s | fastest=%dmin via=%s",
            (datetime.now() - t0).total_seconds(), len(scored),
            bv.price_total, bv.currency, "+".join(bv.carriers), _route(bv), bv.stops_count,
            bv.total_duration_min, bv.layover_min,
            f"{bv.score:.3f}" if bv.score is not None else "-",
            cheapest.price_total, "+".join(cheapest.carriers), _route(cheapest),
            cheapest.stops_count, cheapest.total_duration_min, cheapest.booking_url or "-",
            fastest.total_duration_min, response.split_via or "-",
        )
    return response


def _find_via_airport(itineraries: list[Itinerary]) -> str | None:
    """Return the most common intermediate airport from multi-stop outbound legs."""
    counter: Counter = Counter()
    for it in itineraries:
        out_segs = [s for s in it.segments if s.direction in ("outbound", "")]
        if len(out_segs) >= 2:
            for seg in out_segs[:-1]:
                counter[seg.destination] += 1
    if not counter:
        return None
    via, _count = counter.most_common(1)[0]
    return via


async def run_split_suggestion(req: SearchRequest, via: str, settings: Settings) -> StopoverResponse | None:
    """Public entry point: build a multi-day split suggestion for the given via airport.
    Called from a separate endpoint so it doesn't block the main search response."""
    return await _auto_split_suggestion(req, [], settings, via_override=via)


async def _auto_split_suggestion(
    req: SearchRequest, itineraries: list[Itinerary], settings: Settings,
    via_override: str | None = None,
) -> StopoverResponse | None:
    """Build multi-day split-ticket suggestion entirely in the agent.

    The agent itself constructs the legs — the APIs are NOT asked for split
    tickets. We:
      1. Find the most common via-airport from the search results (e.g. OTP)
      2. Build 4 independent one-way legs with different dates
      3. Search each leg as a DIRECT flight (the via hub is the one allowed
         stop per direction — broken legs must not add their own stops)
      4. Return the cheapest combination

    Only offered when the customer allows ≥1 connection per direction.

    Date strategy (round trip):
      - Leg 1: origin → via   on departure_date        (e.g. TLV→OTP Aug 4)
      - Leg 2: via → dest     on departure_date+N       (try N=1,2,3)
      - Leg 3: dest → via     on return_date-M          (try M=1,2)
      - Leg 4: via → origin   on return_date            (e.g. OTP→TLV Aug 11)
    """
    # A split via one hub adds exactly one stop per direction (you change
    # planes at the via airport). So it's only valid when the customer allows
    # ≥1 connection. If they asked for direct-only (max_connections == 0), a
    # split through OTP would violate that — don't offer it.
    if req.max_connections is not None and req.max_connections < 1:
        return None

    via = via_override or _find_via_airport(itineraries)
    if not via:
        return None

    origin = req.origin.strip().upper()
    destination = req.destination.strip().upper()
    dep: date = req.flight_dates.departure
    ret: date | None = req.flight_dates.ret

    # KiwiRapid + Kayak give regional direct coverage (e.g. Kayak has direct
    # OTP→CLJ that Kiwi lacks) plus Wizz direct LCC fares (TLV↔OTP). Skyscanner
    # is added too so split-leg fares reconcile with what the user sees on
    # Skyscanner — it's slower (cold call), so the per-leg timeout is widened.
    leg_providers = [KiwiRapidProvider(settings), KayakProvider(settings), SkyscannerProvider(settings)]
    if settings.wizz_enabled:
        leg_providers.append(WizzProvider(settings))
    fast_provider = MultiProvider(leg_providers)

    async def _one_leg(orig: str, dest: str, d: date, _attempt: int = 0) -> StopoverLegResult:
        label = f"{orig} → {dest}"
        try:
            itins = await asyncio.wait_for(
                fast_provider.search(
                    origin=orig, destination=dest,
                    departure_date=d.isoformat(), return_date=None,
                    adults=1, non_stop=True,    # split legs must be DIRECT — the
                                                # via hub (e.g. OTP) is itself the
                                                # one allowed stop per direction,
                                                # so a broken leg must add none.
                    included_airlines=None, excluded_airlines=None,
                    currency=settings.currency,
                ),
                timeout=45,   # widened to let the slow Skyscanner cold-call return
            )
            # Enforce direct: providers don't all honor non_stop, so drop any leg
            # itinerary that has its own stops. A split = 4 direct hops via OTP.
            itins = [it for it in itins if it.stops_count == 0]
            if not itins:
                # An empty leg may be a transient upstream miss (429/503/throttle)
                # rather than a true absence of direct flights. Retry once before
                # giving up — a single fixed-leg miss otherwise nulls the whole
                # split and shows a false "no cheaper split" in the UI.
                if _attempt == 0:
                    await asyncio.sleep(1.5)
                    return await _one_leg(orig, dest, d, _attempt + 1)
                return StopoverLegResult(label=label, date=d.isoformat(), options=[], cheapest_price=0.0, currency=settings.currency, error="No direct flight on this leg")
            _apply_pax_pricing(itins, req.traveler_count)
            scored = score_itineraries(sorted(itins, key=lambda x: x.price_total)[:15], settings)
            # Cheapest-first for display so the headline price matches the first card.
            top = sorted(scored[:3], key=lambda it: it.price_total)
            return StopoverLegResult(
                label=label, date=d.isoformat(),
                options=[to_out(it) for it in top],
                cheapest_price=top[0].price_total,
                currency=top[0].currency,
            )
        except asyncio.TimeoutError:
            if _attempt == 0:
                return await _one_leg(orig, dest, d, _attempt + 1)
            return StopoverLegResult(label=label, date=d.isoformat(), options=[], cheapest_price=0.0, currency=settings.currency, error="Timeout")
        except Exception as exc:
            if _attempt == 0:
                await asyncio.sleep(1.5)
                return await _one_leg(orig, dest, d, _attempt + 1)
            return StopoverLegResult(label=label, date=d.isoformat(), options=[], cheapest_price=0.0, currency=settings.currency, error=str(exc)[:80])

    if ret:
        # Try all combinations: fwd_offset 1-6 days, back_offset 1-5 days
        # Deduplicated so the same date pair is only searched once
        offsets = [(fwd, back) for fwd in range(1, 7) for back in range(1, 6)
                   if dep + timedelta(days=fwd) < ret - timedelta(days=back)]

        mid_combos: list[tuple[date, date]] = list({
            (dep + timedelta(days=fwd), ret - timedelta(days=back))
            for fwd, back in offsets
        })

        # Search every UNIQUE leg/date exactly once. Each mid date appears in
        # many combos, so searching per-combo would fire ~5x redundant provider
        # calls and throttle the upstreams (Wizz 429/503, empty results). Keyed
        # by date, legs 2 & 3 collapse to a handful of real searches.
        uniq_mid_dep = sorted({md for md, _ in mid_combos})
        uniq_mid_ret = sorted({mr for _, mr in mid_combos})

        leg1_task = asyncio.create_task(_one_leg(origin, via, dep))
        leg4_task = asyncio.create_task(_one_leg(via, origin, ret))
        leg2_tasks = {d: asyncio.create_task(_one_leg(via, destination, d)) for d in uniq_mid_dep}
        leg3_tasks = {d: asyncio.create_task(_one_leg(destination, via, d)) for d in uniq_mid_ret}

        leg1, leg4 = await asyncio.gather(leg1_task, leg4_task)
        await asyncio.gather(*leg2_tasks.values(), *leg3_tasks.values())
        leg2_map = {d: t.result() for d, t in leg2_tasks.items()}
        leg3_map = {d: t.result() for d, t in leg3_tasks.items()}

        # A split is only real if EVERY leg has a direct flight. The fixed
        # legs 1 & 4 must exist; otherwise there is no valid split to suggest.
        if not leg1.options or not leg4.options:
            return None

        # Pick the cheapest combination that is also CHRONOLOGICALLY VALID:
        # each leg must depart after the previous leg lands (+ connection buffer).
        # Combos where the middle legs have no direct flight, or where no valid
        # time-ordered chain exists, are skipped (never fabricate a $0 leg or an
        # itinerary whose leg 2 departs before leg 1 has landed).
        best: StopoverResponse | None = None
        best_total: float | None = None
        for mid_dep, mid_ret in mid_combos:
            leg2, leg3 = leg2_map[mid_dep], leg3_map[mid_ret]
            if leg2.error or leg3.error or not leg2.options or not leg3.options:
                continue
            legs = [leg1, leg2, leg3, leg4]
            plan = _chronological_plan(legs)
            if plan is None:
                continue   # no time-ordered chain for this date combo
            total, chosen = plan
            if best_total is None or total < best_total:
                best_total = total
                best = StopoverResponse(
                    legs=_reorder_to_plan(legs, chosen),
                    total_price=total,
                    currency=settings.currency,
                )
        return best

    else:
        # One-way: leg1 always on dep, leg2 on dep+1, dep+2, dep+3 — pick cheapest leg2
        leg1 = await _one_leg(origin, via, dep)
        leg2_dates = [dep + timedelta(days=n) for n in range(1, 4)]
        leg2_results = await asyncio.gather(*[_one_leg(via, destination, d) for d in leg2_dates])
        valid = [(r, d) for r, d in zip(leg2_results, leg2_dates) if not r.error and r.options]
        if not valid:
            return None
        # Cheapest leg 2 that still departs after leg 1 lands (+ buffer). A cheap
        # leg 2 that boards before leg 1 arrives is not a real connection.
        best: StopoverResponse | None = None
        best_total: float | None = None
        for r, _ in sorted(valid, key=lambda x: x[0].cheapest_price):
            legs = [leg1, r]
            plan = _chronological_plan(legs)
            if plan is None:
                continue
            total, chosen = plan
            if best_total is None or total < best_total:
                best_total = total
                best = StopoverResponse(
                    legs=_reorder_to_plan(legs, chosen),
                    total_price=total, currency=settings.currency,
                )
        return best


async def run_stopover_search(req: StopoverRequest, settings: Settings) -> StopoverResponse:
    """Search each leg independently (parallel) and combine cheapest per leg."""
    if len(req.legs) < 2:
        raise NoResultsError("At least 2 legs are required for a multi-day stopover search.")

    include_codes = resolve_codes(req.airline_filters.include)
    exclude_codes = resolve_codes(req.airline_filters.exclude)
    provider = get_provider(settings)

    async def _search_one(leg) -> StopoverLegResult:
        label = f"{leg.origin.strip().upper()} → {leg.destination.strip().upper()}"
        try:
            itins = await provider.search(
                origin=leg.origin.strip().upper(),
                destination=leg.destination.strip().upper(),
                departure_date=leg.date,
                return_date=None,       # always one-way per leg
                adults=1,               # per-person pricing (see run_search)
                non_stop=False,
                included_airlines=include_codes or None,
                excluded_airlines=exclude_codes or None,
                currency=settings.currency,
            )
            _apply_pax_pricing(itins, req.traveler_count)
            filtered = apply_filters(
                itins,
                max_connections=req.max_connections,
                include_codes=include_codes,
                exclude_codes=exclude_codes,
                max_price=req.max_price,
                traveler_count=req.traveler_count,
            )
            if not filtered:
                filtered = sorted(itins, key=lambda x: x.price_total)[:10]
            scored = score_itineraries(filtered, settings)
            # Present cheapest-first so the leg's headline ("From $X") matches
            # the first card. Scoring picks the best-value 5, then we sort those
            # by price for display.
            top = sorted(scored[:5], key=lambda it: it.price_total)
            cheapest_price = top[0].price_total if top else 0.0
            currency = top[0].currency if top else settings.currency
            return StopoverLegResult(
                label=label,
                date=leg.date,
                options=[to_out(it) for it in top],
                cheapest_price=cheapest_price,
                currency=currency,
            )
        except Exception as exc:
            return StopoverLegResult(
                label=label,
                date=leg.date,
                options=[],
                cheapest_price=0.0,
                currency=settings.currency,
                error=str(exc),
            )

    results = list(await asyncio.gather(*[_search_one(leg) for leg in req.legs]))
    # Best-effort: reorder each leg's options so the headline chain is time-valid
    # (leg n+1 departs after leg n lands). Only when every leg returned options;
    # otherwise leave as-is (user explicitly requested these legs).
    if all(not r.error and r.options for r in results):
        plan = _chronological_plan(results)
        if plan is not None:
            _, chosen = plan
            results = _reorder_to_plan(results, chosen)
    total_price = sum(r.cheapest_price for r in results)
    return StopoverResponse(
        legs=results,
        total_price=round(total_price, 2),
        currency=settings.currency,
    )
