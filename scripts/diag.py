"""Deep diagnostic: run the real pipeline + each provider for TLV->CLJ."""
import asyncio

from app.config import get_settings
from app.models import SearchRequest, FlightDates, AirlineFilters
from app.search import run_search
from app.providers import KiwiRapidProvider, KayakProvider, SkyscannerProvider

s = get_settings()
print("provider:", s.provider, "| weights stops/price/dur/lay:",
      s.weight_stops, s.weight_price, s.weight_duration, s.weight_layover)

req = SearchRequest(
    origin="TLV", destination="CLJ",
    flight_dates=FlightDates(departure="2026-08-04", ret="2026-08-11"),
    traveler_count=1, airline_filters=AirlineFilters(),
)


async def main():
    r = await run_search(req, s)
    print(f"\n=== MAIN SEARCH: {r.total_considered} considered ===")
    for i, o in enumerate(r.options[:12], 1):
        print(f"{i:2d}. ${o.price_total:6.0f} {('+'.join(o.carriers)):18s} "
              f"stops={o.stops_count} dur={o.total_duration_min/60:4.1f}h "
              f"lay={o.layover_min/60:4.1f}h score={o.score:.3f}")
    bv = r.best_value[0]
    print(f"\nBEST  : {bv.carriers} ${bv.price_total} {bv.stops_count}st "
          f"{bv.total_duration_min/60:.1f}h lay{bv.layover_min/60:.1f}h")
    print(f"CHEAP : {r.cheapest.carriers} ${r.cheapest.price_total} {r.cheapest.stops_count}st")
    print(f"FAST  : {r.fastest.carriers} ${r.fastest.price_total} {r.fastest.total_duration_min/60:.1f}h")
    print("split_suggestion:", "YES" if r.split_suggestion else "NONE")
    if r.split_suggestion:
        ss = r.split_suggestion
        print(f"  split total ${ss.total_price}: " +
              " | ".join(f"{l.label} {l.date} ${l.cheapest_price:.0f}" for l in ss.legs))


asyncio.run(main())
