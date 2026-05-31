from __future__ import annotations

from .models import Itinerary


def apply_filters(
    itineraries: list[Itinerary],
    *,
    max_connections: int | None = None,
    include_codes: list[str],
    exclude_codes: list[str],
    max_price: float | None = None,
    traveler_count: int = 1,
) -> list[Itinerary]:
    """Strict user-requested post-fetch filtering.

    - max_connections: max stops PER DIRECTION (uses max_stops_per_dir, not the
      combined stops_count which sums outbound + inbound and would incorrectly
      reject valid 1-stop round trips).
    - Include: keep only if EVERY segment carrier is in the include list.
    - Exclude: drop if ANY segment carrier is in the exclude list.
    - Max Price: per-person budget. Provider prices are already per-person so
      no division is needed; traveler_count is kept for future providers that
      return group totals.
    """
    inc = set(include_codes)
    exc = set(exclude_codes)
    out: list[Itinerary] = []

    for it in itineraries:
        # Use max stops in a single direction.
        # If max_stops_per_dir was not populated by the transform (-1 sentinel),
        # derive it from segment directions. For one-way or unlabelled segments
        # fall back to stops_count directly (already per-direction in those cases).
        if it.max_stops_per_dir >= 0:
            stops_to_check = it.max_stops_per_dir
        elif it.segments:
            dir_counts: dict[str, int] = {}
            for s in it.segments:
                d = s.direction or "outbound"
                dir_counts[d] = dir_counts.get(d, 0) + 1
            # stops = segments_in_direction - 1
            stops_to_check = max((c - 1 for c in dir_counts.values()), default=it.stops_count)
        else:
            stops_to_check = it.stops_count
        if max_connections is not None and stops_to_check > max_connections:
            continue
        if max_price is not None and it.price_total > max_price:
            continue

        seg_carriers = {s.carrier_code for s in it.segments}
        if inc and not seg_carriers.issubset(inc):
            continue
        if exc and seg_carriers & exc:
            continue

        out.append(it)

    return out


def prune_unreasonable(itineraries: list[Itinerary]) -> list[Itinerary]:
    """Drop itineraries no human would call 'best value'.

    Providers return junk for short/medium routes: 30-40h trips and overnight
    self-transfers with 15h+ layovers, often as the cheapest fare. Left in, they
    poison the normalized score (huge outliers compress every real option toward
    one end), so the optimizer crowns absurd itineraries. We prune relative to
    the *fastest* real option found, which adapts to short vs long haul:

      - keep total travel time <= max(fastest * 2.5, fastest + 6h)
      - keep total layover    <= 10h

    Always keeps at least the 5 shortest so a sparse route never returns empty.
    """
    if len(itineraries) <= 5:
        return itineraries

    durations = [it.total_duration_min for it in itineraries if it.total_duration_min > 0]
    if not durations:
        return itineraries
    fastest = min(durations)

    dur_cap = max(fastest * 2.5, fastest + 360)
    layover_cap = 600  # 10h

    kept = [
        it for it in itineraries
        if (it.total_duration_min <= 0 or it.total_duration_min <= dur_cap)
        and it.layover_min <= layover_cap
    ]

    if not kept:
        # Last resort: nothing survived both caps — return shortest 5 by duration
        # (still honour layover cap if possible, else take anything).
        candidates = sorted(
            [it for it in itineraries if it.layover_min <= layover_cap],
            key=lambda it: (it.total_duration_min or 1e9),
        )
        kept = candidates[:5] or sorted(itineraries, key=lambda it: it.total_duration_min or 1e9)[:5]
    return kept
