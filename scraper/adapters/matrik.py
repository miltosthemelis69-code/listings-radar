"""Adapter for matrik.gr (custom site by Bluchip, fed by pms.matrik.gr).

The search page posts its form to /website/b-framework/models/search_property.php
(isocode=el, filters[...]) and gets back an HTML fragment that embeds every result of the
page as JSON: myJSON.properties = JSON.parse('[{id, code, transaction_type_id, sub, pref, mun,
area, rooms, sqm, price, propertyURL, img_src}, ...]'). The fragment also states the total
("893 ακίνητα"). transaction_type 1 = sale, property_category 0 = all, sort 6 = newest first,
up to 100 per page. Optional site key "prefecture": "108,109,110" limits to Thessaloniki
(108 centre, 109 suburbs, 110 rest of the prefecture; 196 is Chalkidiki).
"""
import json
import re
import time

from scraper.common import REQUEST_DELAY, _session, clean

MAX_PAGES = 30
PER_PAGE = 100


def _post(url, data):
    """POST politely; fetch() in common.py only does GET."""
    for attempt in range(2):
        try:
            time.sleep(REQUEST_DELAY)
            r = _session().post(url, data=data, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception:
            if attempt == 1:
                raise


def _filters(page, prefecture=0):
    f = {"property_category": 0, "property_subcategory": 0, "transaction_type": 1, "prefecture": prefecture,
         "municipality": 0, "area": 0, "rooms": 0, "price_from": 0, "price_to": 0, "sqm_from": 0,
         "sqm_to": 0, "first_at_sea": 0, "opportunities_in_chalkidiki": 0, "holiday_property": 0,
         "student_use": 0, "sort": 6, "properties_per_page": PER_PAGE, "pagination": page}
    return {"isocode": "el", **{f"filters[{k}]": v for k, v in f.items()}}


def parse_row(row):
    pref = clean(row.get("pref") or "")      # "Θεσσαλονίκη - Κέντρο", "Χαλκιδική"
    mun = clean(row.get("mun") or "")        # "Κέντρο Θεσσαλονίκης", "Καλαμαριά"
    area = clean(row.get("area") or "")      # "Ιστορικό Κέντρο"
    city = mun or pref.split(" - ")[0]
    sub = clean(row.get("sub") or "")
    if sub == "Στούντιο":
        sub = "Studio"
    place = ", ".join(p for p in (area, city) if p)
    return {
        "source_id": str(row["id"]),
        "code": clean(row.get("code") or "") or str(row["id"]),
        "url": row["propertyURL"].replace("http://", "https://", 1),
        "title": " ".join(p for p in (sub, "προς πώληση", place) if p),
        "type": sub or None,
        "deal": {1: "sale", 2: "rent"}.get(row.get("transaction_type_id")),
        "price": int(row["price"]) if row.get("price") else None,
        "sqm": float(row["sqm"]) if row.get("sqm") else None,
        "bedrooms": int(row["rooms"]) if row.get("rooms") else None,
        "city": city,
        "area": area,
        "location": place,
        "available_from": None,
        "image": row.get("img_src") or None,
        "description": clean(row.get("title") or ""),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    url = f"{base_url}/website/b-framework/models/search_property.php"
    listings = {}
    total = None
    complete = False
    for page in range(1, MAX_PAGES + 1):
        html = _post(url, _filters(page, site.get("prefecture", 0)))
        m = re.search(r"(\d+)\s*ακίνητα", html)
        if m:
            total = int(m.group(1))
        m = re.search(r"myJSON\.properties = JSON\.parse\('(.*?)'\);", html, re.S)
        rows = json.loads(m.group(1).replace("\\'", "'")) if m else []
        new_on_page = 0
        for row in rows:
            try:
                item = parse_row(row)
            except Exception as e:
                print(f"  [{site['id']}] skipped listing {row.get('id')}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0 or (total is not None and len(listings) >= total):
            complete = True
            break
    return list(listings.values()), complete
