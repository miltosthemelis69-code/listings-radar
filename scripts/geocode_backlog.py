"""Look up every place name not in the data file's "geo" table yet (one-off; normal runs do 150)."""
from pathlib import Path

from scraper import store
from scraper.geo import locate
from scraper.zones import assign

path = Path("data/listings.json")
db = store.load(path)
assign(db["listings"].values())
locate(db, [l for l in db["listings"].values() if l.get("active")], max_lookups=100000)
store.save(path, db)
