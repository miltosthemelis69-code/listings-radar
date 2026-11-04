"""Read every listing page not read yet (floor, elevator, map point) in one go; normal runs do 400 per agency."""
from datetime import datetime, timezone
from pathlib import Path

from scraper import store
from scraper.details import enrich
from scraper.geo import locate
from scraper.zones import assign

path = Path("data/listings.json")
db = store.load(path)
active = [l for l in db["listings"].values() if l.get("active")]
assign(active)
enrich(active, datetime.now(timezone.utc).isoformat(timespec="seconds"), max_per_site=100000)
locate(db, active)
store.save(path, db)
