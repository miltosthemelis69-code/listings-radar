"""Try one site config without touching data/listings.json or sites.json.

Usage: .venv/bin/python -m scripts.try_site '<site config JSON>'
   or: .venv/bin/python -m scripts.try_site candidates/<file>.json

Prints how many listings the adapter read, how many are for sale after the runner's
own cleanup (rentals dropped, types/places standardised), missing fields, and samples.
"""
import collections
import importlib
import json
import sys
from pathlib import Path

from scraper.run import collect


def main():
    arg = sys.argv[1]
    site = json.loads(Path(arg).read_text()) if arg.endswith(".json") else json.loads(arg)
    importlib.import_module(f"scraper.adapters.{site['adapter']}")  # fail fast on a bad adapter name
    items, complete = collect(site, None)
    print(f"site: {site['id']}  adapter: {site['adapter']}  complete scan: {complete}")
    print(f"for-sale listings after cleanup: {len(items)}")
    if not items:
        return
    ids = collections.Counter(i["source_id"] for i in items)
    dupes = [k for k, v in ids.items() if v > 1]
    print(f"unique source_ids: {len(ids)}{'  DUPLICATE IDS: ' + str(dupes[:5]) if dupes else ''}")
    for f in ["price", "sqm", "bedrooms", "type", "city", "area", "image", "url"]:
        print(f"  missing {f:9}: {sum(1 for i in items if not i.get(f))}")
    print("  types :", collections.Counter(i["type"] for i in items).most_common(8))
    print("  cities:", collections.Counter(i["city"] for i in items).most_common(6))
    for i in items[:4]:
        print("  sample:", {k: i.get(k) for k in ["source_id", "code", "title", "type", "price", "sqm", "bedrooms", "location", "url"]})


if __name__ == "__main__":
    main()
