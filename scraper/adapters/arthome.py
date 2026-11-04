"""Adapter for arthome-realestate.gr (Next.js front end over a JSON API).

The site's own pages call https://arthome-app-p7eyz.ondigitalocean.app/api/properties
?lang=el&intent=SALE&locationIds=<dbId>&page=N (100 per page, newest first, meta.total).
ART.HOME also lists Athens properties, so the config's `locations` maps the site's
Thessaloniki location ids (nomos_108 Δήμος Θεσσαλονίκης, nomos_109 περιφερειακοί δήμοι,
nomos_110 υπόλοιπο νομού) to a city name; null means "the listing's region is the city".
Detail pages are /el/properties/<id>.
"""
import json

from scraper.common import clean, fetch, normalize

API = "https://arthome-app-p7eyz.ondigitalocean.app/api/properties"
MAX_PAGES = 50
DEFAULT_LOCATIONS = {"nomos_108": "Θεσσαλονίκη", "nomos_109": None, "nomos_110": None}


def parse_property(p, base_url, city_name):
    region, loc = clean(p.get("region")), clean(p.get("location"))
    if city_name:
        city = city_name
        area = ", ".join(x for x in dict.fromkeys([loc, region]) if x and normalize(x) != normalize(city))
    else:
        city = region
        area = loc if normalize(loc) != normalize(region) else ""
    ptype = clean(p.get("category"))
    sqm = p.get("sqm")
    intent = (p.get("intent") or "").upper()
    return {
        "source_id": str(p["id"]),
        "code": str(p.get("code") or p["id"]),
        "url": f"{base_url}/el/properties/{p['id']}",
        "title": f"{ptype} {sqm} τ.μ." if sqm else ptype,
        "type": ptype or None,
        "deal": "sale" if intent == "SALE" else ("rent" if intent == "RENT" else None),
        "price": int(p["price"]) if p.get("price") else None,
        "sqm": float(sqm) if sqm else None,
        "bedrooms": p.get("bedrooms") or None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": p.get("primaryImage") or None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    locations = site.get("locations") or DEFAULT_LOCATIONS
    listings, complete = {}, True
    for loc_id, city_name in locations.items():
        for page in range(1, MAX_PAGES + 1):
            data = json.loads(fetch(API, params={"lang": "el", "intent": "SALE", "locationIds": loc_id, "page": page}))
            new_on_page = 0
            for p in data.get("data", []):
                try:
                    item = parse_property(p, base_url, city_name)
                except Exception as e:
                    print(f"  [{site['id']}] skipped property {p.get('id')}: {e}")
                    continue
                if item["source_id"] not in listings:
                    listings[item["source_id"]] = item
                    new_on_page += 1
            if new_on_page == 0 or page >= (data.get("meta") or {}).get("totalPages", 0):
                break
        else:
            complete = False
    # several location queries: newest first = highest id first
    items = sorted(listings.values(), key=lambda i: -int(i["source_id"]))
    for rank, item in enumerate(items, 1):
        item["site_rank"] = rank
    return items, complete
