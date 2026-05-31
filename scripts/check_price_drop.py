"""Force a price-drop scenario to verify the email alert fires end-to-end."""
import asyncio, sys, logging
logging.basicConfig(level=logging.INFO)

sys.path.insert(0, ".")
from app import watcher
from app.config import get_settings

watcher._load()
watches = watcher.list_watches()
print("Watches loaded:", [(w["id"], w["email"], w["best_price"]) for w in watches])

# Inflate best_price on first adibend watch so current search looks like a drop
target = None
for wid, w in watcher._watches.items():
    if w["email"] == "adibend@gmail.com":
        target = w
        break

if not target:
    print("No adibend watch found.")
    sys.exit(1)

old = target["best_price"]
target["best_price"] = 9999.0
print(f"Inflated best_price {old} -> 9999.0 on watch {target['id']}")


async def run():
    await watcher._check_watch(target)
    print(f"Check done. new best_price={target.get('best_price')}, last_checked={target.get('last_checked')}")


asyncio.run(run())
