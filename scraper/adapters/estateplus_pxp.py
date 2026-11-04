"""Adapter for the estateplus.gr "pxp" map theme (clockrealestate.gr, cozyestate.gr).

/el/properties/Greece?listingType=for+sale is an empty shell: its map script POSTs the
search form to /ajax/show-properties.php and draws the JSON it gets back
{total, total_pages, current_page, properties:[{id, type, size, purpose, price, rooms,
images, lat, lon, ...}]}, 20 per page (page number sent as `start`). The endpoint ignores
GET, so this adapter POSTs (same user agent and 1-second delay as scraper.common.fetch).

The JSON has no place names, so the scan goes area by area: for each `areas` id (the
site's region list: 108 Θεσσαλονίκη - Κέντρο, 109 Περιφ. Δήμοι, 110 Υπόλ. Νομού,
196 Χαλκιδική) it reads the region's municipalities/neighbourhoods from
/ajax/updateAreas.php and queries each one, which names the listing's place. Listings in
regions not listed are not read.
"""
import json
import re
import threading
import time

import requests

from scraper.common import REQUEST_DELAY, USER_AGENT, clean, deal_from_text, parse_int, parse_price, parse_sqm

MAX_PAGES = 100
# regions whose sub-areas are neighbourhoods of one city rather than municipalities
CITY_REGIONS = {"108": "Θεσσαλονίκη"}
BOUNDS = {"bounds[min_lat]": 30, "bounds[max_lat]": 45, "bounds[min_lng]": 15, "bounds[max_lng]": 32}  # all of Greece

_sessions = {}


def post(url, data):
    key = threading.get_ident()
    if key not in _sessions:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "el-GR,el;q=0.9"})
        _sessions[key] = s
    for attempt in range(2):
        try:
            time.sleep(REQUEST_DELAY)
            r = _sessions[key].post(url, data=data, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt == 1:
                raise


def form(fields, page):
    data = dict(BOUNDS)
    for i, (name, value) in enumerate(fields):
        data[f"formData[{i}][name]"] = name
        data[f"formData[{i}][value]"] = value
    if page > 1:
        data["start"] = page
    return data


def sub_areas(base_url, area_id):
    html = post(f"{base_url}/ajax/updateAreas.php", {"selectpicker": "true", "areaID": area_id})
    return [(v, clean(n)) for v, n in re.findall(r'<option value="(\d+)">([^<]*)</option>', html)]


def parse_row(row, base_url, city, area):
    ptype = clean(row.get("type")) or None
    size = row.get("size")
    images = row.get("images") or []
    return {
        "source_id": str(row["id"]),
        "code": str(row["id"]),
        "url": f"{base_url}/el/property/{row['id']}",
        "title": f"{ptype or 'Ακίνητο'} {size} τ.μ." if size else (ptype or ""),
        "type": ptype,
        "deal": deal_from_text(row.get("purpose") or ""),
        "price": parse_price(row.get("price")) if row.get("price") else None,
        "sqm": parse_sqm(str(size)) if size else None,
        "bedrooms": parse_int(str(row["rooms"])) if row.get("rooms") else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": images[0] if images else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    complete = True
    for area_id in site.get("areas", ["108", "109", "110", "196"]):
        area_id = str(area_id)
        for geo_id, geo_name in sub_areas(base_url, area_id):
            if area_id in CITY_REGIONS:
                city, area = CITY_REGIONS[area_id], geo_name
            else:
                city, area = re.sub(r"^Δ\.\s*", "", geo_name), ""
            fields = [("listingType", "for sale"), ("areaID", area_id), ("geographyId[]", geo_id)]
            for page in range(1, MAX_PAGES + 1):
                try:
                    data = json.loads(post(f"{base_url}/ajax/show-properties.php", form(fields, page)))
                except (requests.RequestException, ValueError) as e:
                    if getattr(getattr(e, "response", None), "status_code", None) == 429:
                        raise  # rate-limited: stop instead of carrying on with the next area
                    print(f"  [{site['id']}] {geo_name} page {page}: {e}")
                    complete = False
                    break
                for row in data.get("properties") or []:
                    sid = str(row.get("id"))
                    if sid in listings:
                        continue
                    try:
                        listings[sid] = parse_row(row, base_url, city, area)
                    except Exception as e:
                        print(f"  [{site['id']}] skipped listing {sid}: {e}")
                if page >= int(data.get("total_pages") or 0):
                    break
    items = sorted(listings.values(), key=lambda i: -int(i["source_id"]))  # newest (highest id) first
    for rank, item in enumerate(items, 1):
        item["site_rank"] = rank
    return items, complete
