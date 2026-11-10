"""Scrape every site in sites.json, merge into data/listings.json, alert on new matches.

Usage: python -m scraper.run [--only SITE_ID] [--no-notify] [--full]
"""
import argparse
import importlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from scraper.common import KEEP_TYPES, canonical_type, has_accents, normalize, strip_admin
from scraper.dedupe import assign_groups
from scraper.details import enrich as enrich_details
from scraper.notify import notify_new
from scraper import store
from scraper.geo import locate
from scraper.mailalerts import forward as forward_mail_alerts
from scraper.zones import assign as assign_zones

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "listings.json"


def load_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def standardize(item):
    """Same names across agencies: one list of property types, no 'Δήμος …' prefixes."""
    item["type"] = canonical_type(item.get("type"), item.get("title"), item.get("description"))
    item["city"] = strip_admin(item.get("city") or "")
    item["area"] = ", ".join(strip_admin(p) for p in (item.get("area") or "").split(",") if p.strip())


def collect(site, known_ids):
    """Scrape one site and clean its items: sales only, standard names."""
    adapter = importlib.import_module(f"scraper.adapters.{site['adapter']}")
    items, complete = adapter.scrape(site, known_ids=known_ids)
    if site.get("deal"):  # the site's own sale filter beats a mistyped title ("Προς Ενοικίαση" at €59.000)
        for i in items:
            i["deal"] = site["deal"]
    items = [i for i in items if i.get("deal") != "rent"]  # buying only; sites without a sale filter still list rentals
    for i in items:
        standardize(i)
    items = [i for i in items if i["type"] in KEEP_TYPES]  # flats, studios, offices, buildings, workshops only
    return items, complete


def fix_place_spelling(listings):
    """Sites that write in capitals lose accents ('ΙΩΑΝΝΙΝΑ' -> 'Ιωαννινα'). Use the accented
    spelling another agency uses for the same place, so filters show one entry per place."""
    variants = defaultdict(Counter)
    for l in listings:
        for name in [l["city"], *l["area"].split(", ")]:
            if name:
                variants[normalize(name)][name] += 1
    best = {}
    for key, names in variants.items():
        good = [n for n in names if has_accents(n) and not n.isupper()]
        best[key] = max(good, key=names.get) if good else max(names, key=names.get).title()
    for l in listings:
        l["city"] = best.get(normalize(l["city"]), l["city"])
        l["area"] = ", ".join(best.get(normalize(p), p) for p in l["area"].split(", ") if p)
        l["location"] = ", ".join(x for x in [l["area"], l["city"]] if x)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="scrape just these site ids (comma-separated)")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--full", action="store_true", help="force a full scan of every site")
    args = ap.parse_args()

    sites = load_json(ROOT / "sites.json", [])
    # on a public repo the saved searches can live in a secret instead of preferences.json
    preferences = json.loads(os.environ["PREFERENCES_JSON"]) if os.environ.get("PREFERENCES_JSON") \
        else load_json(ROOT / "preferences.json", [])
    db = store.load(DATA_FILE)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_listings = []

    for s in sites:  # the data file keeps each agency's city instead of repeating it per listing
        db["sites"].setdefault(s["id"], {"name": s["name"], "url": s["base_url"]})["region"] = s.get("region", "Ιωάννινα")
    sites = [s for s in sites if not args.only or s["id"] in args.only.split(",")]

    # slow sites: only read the newest pages, with a full scan every `full_scan_hours`
    known = {}
    for site in sites:
        state = db["sites"].get(site["id"], {})
        known[site["id"]] = None
        if site.get("full_scan_hours") and not args.full and state.get("first_import") and state.get("last_full_scan"):
            hours = (datetime.fromisoformat(now) - datetime.fromisoformat(state["last_full_scan"])).total_seconds() / 3600
            if hours < site["full_scan_hours"]:
                known[site["id"]] = {l["source_id"] for l in db["listings"].values() if l["site"] == site["id"]}

    # every site is a different server, so scrape them in parallel (each still waits 1s between its own pages)
    with ThreadPoolExecutor(max_workers=16) as pool:
        jobs = {s["id"]: pool.submit(collect, s, known[s["id"]]) for s in sites}

    for site in sites:
        state = db["sites"].get(site["id"], {})
        first_run_for_site = not state.get("first_import")
        site_uids = {u for u, l in db["listings"].items() if l["site"] == site["id"]}
        prev_active = sum(1 for u in site_uids if db["listings"][u].get("active") and db["listings"][u].get("type") in KEEP_TYPES)

        print(f"[{site['id']}] {'incremental' if known[site['id']] is not None else 'full'} scrape of {site['base_url']} ...")
        try:
            items, complete = jobs[site["id"]].result()
            # a blocked/broken page can look like "everything was removed"; don't trust a sudden collapse
            if complete and prev_active >= 10 and len(items) < prev_active * 0.5:
                raise RuntimeError(f"only {len(items)} listings vs {prev_active} last time, skipping update")
        except Exception as e:
            print(f"[{site['id']}] FAILED: {e}")
            db["sites"].setdefault(site["id"], {})["last_error"] = f"{now}: {e}"
            continue

        seen_uids = set()
        for item in items:
            uid = f"{site['id']}:{item['source_id']}"
            seen_uids.add(uid)
            item.update(uid=uid, site=site["id"], site_name=site["name"], region=site.get("region", "Ιωάννινα"))
            old = db["listings"].get(uid)
            if old is None:
                item.update(first_seen=now, last_seen=now, active=True, price_history=[[now, item["price"]]])
                if not first_run_for_site:  # don't alert on the initial import
                    new_listings.append(item)
            else:
                history = old.get("price_history", [])
                if item["price"] != old.get("price"):
                    history.append([now, item["price"]])
                item.update(first_seen=old["first_seen"], last_seen=now, active=True, price_history=history)
                for key in ("floor", "elevator", "details_checked", "coords", "coords_checked"):  # read once from the listing's page
                    if key in old:
                        item[key] = old[key]
                if not old.get("active", True):  # removed earlier, now back on the market
                    item["relisted_at"] = now
                    new_listings.append(item)
            db["listings"][uid] = item

        # after a full scan, anything we didn't see has been removed / sold / rented
        if complete:
            for uid in site_uids - seen_uids:
                db["listings"][uid]["active"] = False

        active = sum(1 for u in site_uids | seen_uids if db["listings"][u].get("active"))
        db["sites"][site["id"]] = {
            "name": site["name"], "url": site["base_url"],
            "first_import": state.get("first_import") or now,
            "last_full_scan": now if complete else state.get("last_full_scan"),
            "last_success": now, "count": active, "last_error": None, "region": site.get("region", "Ιωάννινα"),
        }
        site_new = [i for i in new_listings if i["site"] == site["id"]]
        print(f"[{site['id']}] {len(items)} listings read, {active} active, {len(site_new)} new")
        for i in site_new:
            tag = "RELISTED" if i.get("relisted_at") else "NEW"
            print(f"  {tag:8} {str(i['code']):7} €{i['price'] or 0:>9,} {i['sqm'] or 0:>6} m²  {i['title']} · {i['location']}")

    db["updated_at"] = now
    # types we no longer keep (plots, houses, shops …): gone from the data, not "removed"
    db["listings"] = {u: l for u, l in db["listings"].items() if l.get("type") in KEEP_TYPES}
    fix_place_spelling(db["listings"].values())
    assign_zones(db["listings"].values())
    locate(db, [l for l in db["listings"].values() if l.get("active")])
    enrich_details(db["listings"].values(), now)
    groups = assign_groups(list(db["listings"].values()))
    print(f"{sum(len(g) for g in groups.values())} active listings = {len(groups)} unique properties "
          f"({sum(1 for g in groups.values() if len(g) > 1)} listed by more than one agency)")
    store.save(DATA_FILE, db)

    # one alert per property, and none when another agency already had it listed
    new_uids = {l["uid"] for l in new_listings}
    new_properties, done = [], set()
    for l in new_listings:
        members = groups.get(l.get("group"), [l])
        if l.get("group") in done:
            continue
        done.add(l.get("group"))
        known = [m for m in members if m["uid"] not in new_uids]
        if known:
            print(f"  no alert for {l['site_name']} {l['code']}: already listed by {', '.join(m['site_name'] for m in known)}")
            continue
        new_properties.append(members)

    if not args.no_notify:
        sent = notify_new(new_properties, preferences)
        print(f"alerts sent: {sent}")
        # Spitogatos / xe.gr alert emails cover the agencies we can't scan
        print(f"portal email alerts sent: {forward_mail_alerts(db, preferences)}")
        store.save(DATA_FILE, db)


if __name__ == "__main__":
    main()
