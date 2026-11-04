"""Adapter for skylineproperty.gr (Next.js front end, Convex backend).

The /buy page loads its grid with the public Convex query `properties:search`
({"intent": "sell"}), which returns every for-sale property in one response:
slug, title, subcategory, price (missing = "price on request"), sizeSqm, bedrooms,
areaName, regionName, heroUrl, status. Detail pages are /buy/<slug>.
Convex queries are POSTed to https://<deployment>.convex.cloud/api/query.
"""
import json
import time

import requests

from scraper.common import USER_AGENT, REQUEST_DELAY, clean

CONVEX = "https://clean-peacock-200.convex.cloud/api/query"
TYPES = {
    "apartment": "Διαμέρισμα", "detached_house": "Μονοκατοικία", "villa": "Βίλα", "maisonette": "Μεζονέτα",
    "hotel": "Ξενοδοχείο", "land": "Οικόπεδο", "plot": "Οικόπεδο", "office": "Γραφείο", "store": "Κατάστημα",
    "warehouse": "Αποθήκη", "industrial": "Βιομηχανικός χώρος", "building": "Κτίριο", "parking": "Parking",
}


def convex_query(path, args):
    time.sleep(REQUEST_DELAY)
    r = requests.post(CONVEX, json={"path": path, "args": args, "format": "json"},
                      headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "success":
        raise RuntimeError(f"convex query failed: {data.get('errorMessage')}")
    return data["value"]


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    value = convex_query("properties:search", {"intent": "sell"})
    items = []
    # newest first
    for p in sorted(value.get("properties", []), key=lambda p: -(p.get("createdAt") or 0)):
        if p.get("status") not in (None, "available"):
            continue  # sold / under offer
        sub = p.get("subcategory") or p.get("category") or ""
        region = clean(p.get("regionName")).replace("Περιφερειακή Ενότητα ", "").replace("Μητροπολιτική Ενότητα ", "")
        region = {"Καβάλας": "Καβάλα", "Χαλκιδικής": "Χαλκιδική", "Θεσσαλονίκης": "Θεσσαλονίκη", "Κορινθίας": "Κορινθία"}.get(region, region)
        area = clean(p.get("areaName"))
        items.append({
            "source_id": p["_id"],
            "code": p["slug"],
            "url": f"{base_url}/buy/{p['slug']}",
            "title": clean(p.get("title")),
            "type": TYPES.get(sub, sub.replace("_", " ")) or None,
            "deal": "sale",
            "price": int(p["price"]) if p.get("price") else None,
            "sqm": float(p["sizeSqm"]) if p.get("sizeSqm") else None,
            # hotels report their room count as "bedrooms"
            "bedrooms": int(p["bedrooms"]) if p.get("bedrooms") and p.get("category") == "residential" else None,
            "city": region,
            "area": area,
            "location": ", ".join(x for x in [area, region] if x),
            "available_from": None,
            "image": p.get("heroUrl") or None,
            "description": ", ".join(p.get("features") or [])[:200],
            "site_rank": len(items) + 1,
        })
    return items, True
