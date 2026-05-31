"""Ad-hoc verify: run each RapidAPI scraper alone + multi merge. TLV->CLJ."""
import asyncio
import time

from app.config import get_settings
from app.providers import KiwiRapidProvider, KayakProvider, MultiProvider

KW = dict(
    origin="TLV",
    destination="CLJ",
    departure_date="2026-08-04",
    return_date="2026-08-11",
    adults=1,
    non_stop=False,
    included_airlines=None,
    excluded_airlines=None,
    currency="USD",
)


async def run_one(name, provider):
    t0 = time.perf_counter()
    try:
        itins = await provider.search(**KW)
        dt = time.perf_counter() - t0
        print(f"[{name}] OK  {len(itins)} itineraries  {dt:.1f}s")
        for it in sorted(itins, key=lambda x: x.price_total)[:3]:
            carr = ",".join(it.carriers)
            print(f"    {it.price_total} {it.currency}  {carr}  stops={it.stops_count}")
        return itins
    except Exception as e:
        dt = time.perf_counter() - t0
        print(f"[{name}] FAIL {type(e).__name__}: {e}  {dt:.1f}s")
        return []


async def main():
    s = get_settings()
    print(f"provider config = {s.provider}, key set = {bool(s.rapidapi_key)}\n")
    kiwi = KiwiRapidProvider(s)
    kayak = KayakProvider(s)
    await run_one("kiwi_rapid", kiwi)
    await run_one("kayak", kayak)
    multi = MultiProvider([KiwiRapidProvider(s), KayakProvider(s)])
    merged = await run_one("multi", multi)
    print(f"\nmulti merged total = {len(merged)}")


if __name__ == "__main__":
    asyncio.run(main())
