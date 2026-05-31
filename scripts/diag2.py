"""Inspect per-direction structure + why split-suggestion is empty."""
import asyncio

from app.config import get_settings
from app.models import SearchRequest, FlightDates, AirlineFilters
from app.providers import get_provider
from app.search import _find_via_airport, run_stopover_search
from app.models import StopoverLegRequest, StopoverRequest

s = get_settings()


async def main():
    prov = get_provider(s)
    its = await prov.search(
        origin="TLV", destination="CLJ",
        departure_date="2026-08-04", return_date="2026-08-11",
        adults=1, non_stop=False, included_airlines=None,
        excluded_airlines=None, currency="USD",
    )
    print("raw itineraries:", len(its))
    # show direction breakdown of first 3
    for it in its[:3]:
        dirs = {}
        for seg in it.segments:
            dirs.setdefault(seg.direction or "?", []).append(
                f"{seg.origin}->{seg.destination}({seg.duration_min}m,lay{seg.layover_after_min}m)"
            )
        print(f"\n${it.price_total} stops={it.stops_count} max_per_dir={it.max_stops_per_dir} "
              f"dur={it.total_duration_min}m lay={it.layover_min}m")
        for d, segs in dirs.items():
            print(f"   {d}: {' '.join(segs)}")

    via = _find_via_airport(its)
    print("\nDETECTED via airport:", via)

    # try the user's exact multi-day split: TLV->OTP 8/4, OTP->CLJ 8/6, CLJ->OTP 8/10, OTP->TLV 8/11
    legs = [
        StopoverLegRequest(origin="TLV", destination="OTP", date="2026-08-04"),
        StopoverLegRequest(origin="OTP", destination="CLJ", date="2026-08-06"),
        StopoverLegRequest(origin="CLJ", destination="OTP", date="2026-08-10"),
        StopoverLegRequest(origin="OTP", destination="TLV", date="2026-08-11"),
    ]
    req = StopoverRequest(legs=legs, traveler_count=1, airline_filters=AirlineFilters())
    r = await run_stopover_search(req, s)
    print(f"\nUSER MULTI-DAY SPLIT total=${r.total_price}:")
    for l in r.legs:
        if l.error:
            print(f"   {l.label} {l.date}: ERROR {l.error[:80]}")
        else:
            o = l.options[0] if l.options else None
            c = '+'.join(o.carriers) if o else '?'
            print(f"   {l.label} {l.date}: ${l.cheapest_price:.0f} {c}")


asyncio.run(main())
