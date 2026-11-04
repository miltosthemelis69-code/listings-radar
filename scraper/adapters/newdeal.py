"""Adapter for newdeal.gr (New Deal Group network; custom PHP site).

The search pages fill their grid by POSTing the filter form to
/el/ajax/listings/<page>/date_min (date_min = newest first), 12 listings per page, JSON
{total, total_pages, listings:[{id, url, propertyType, location, price, size, rooms,
photo, listing_type, ...}]}. The endpoint ignores GET parameters, so this adapter POSTs
(same user agent and 1-second delay as scraper.common.fetch).
New Deal is a Greece-wide network; `locations` in the config limits the scan to the
Thessaloniki prefecture (108 Δήμος Θεσσαλονίκης, 109 περιφερειακοί δήμοι, 110 υπόλοιπο
νομού), which is served by the Thessaloniki office (Power Deal, Τσιμισκή 33; URLs "6-...").
"""
import time
from urllib.parse import urljoin

import requests

from scraper.common import REQUEST_DELAY, USER_AGENT, clean, deal_from_text, parse_int, parse_price, parse_sqm

MAX_PAGES = 150
_session = None


def post(url, data):
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "el-GR,el;q=0.9"})
    for attempt in range(2):
        try:
            time.sleep(REQUEST_DELAY)
            r = _session.post(url, data=data, timeout=30)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == 1:
                raise


def parse_row(row, base_url):
    # location: "<neighbourhood>, <sub-area or municipality>, Θεσσαλονίκη - Δήμος | Περιφ/κοί δήμοι | Υπόλ. Νομού"
    parts = [clean(p) for p in (row.get("location") or "").split(",") if clean(p)]
    zone = parts[-1] if parts else ""
    rest = list(dict.fromkeys(parts[:-1]))
    if zone.endswith("Δήμος") or not rest:
        city, area = zone.split(" - ")[0], ", ".join(rest)
    else:  # suburbs: the middle part is the municipality
        city, area = rest[-1], ", ".join(rest[:-1])
    ptype = clean(row.get("propertyType"))
    size = row.get("size")
    return {
        "source_id": row["id"],
        "code": row["id"],
        "url": urljoin(base_url + "/", row["url"]),
        "title": f"{ptype} {size} τ.μ." if size else ptype,
        "type": ptype or None,
        "deal": deal_from_text(row.get("listing_type") or row.get("type") or ""),
        "price": parse_price(row.get("price")),
        "sqm": parse_sqm(row.get("size")) if row.get("size") else None,
        "bedrooms": parse_int(row.get("rooms")) if row.get("rooms") else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": row.get("photo") or None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    form = {"type": "buy", "location[]": [str(x) for x in site.get("locations", [108, 109, 110])]}
    listings, complete = {}, True
    for page in range(1, MAX_PAGES + 1):
        data = post(f"{base_url}/el/ajax/listings/{page}/date_min", form)
        new_on_page = 0
        for row in data.get("listings") or []:
            try:
                item = parse_row(row, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped listing on page {page}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0 or page >= int(data.get("total_pages") or 0):
            break
    else:
        complete = False
    return list(listings.values()), complete
