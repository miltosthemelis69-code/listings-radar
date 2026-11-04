"""Adapter for elxis.com (national network, Laravel + Inertia.js), limited to one area.

An area page such as /gr/area/thessaloniki-regional-unit?page=N is server-rendered with the
whole Inertia page state in <div id="app" data-page="{json}">; props.properties.data holds
that area's listings (12 a page) and props.properties.meta the total and last page. Elxis
only sells (no rentals). Rows carry id, name, slug, price, type ("Διαμέρισμα", "Βίλα",
"Σπίτι"), city.name, area.name, details [{type: bedrooms|size|plot_size, value}],
featured_image.url, detail_url, is_available, sold_at, published_at.
Site key "area_slug" picks the area (default "thessaloniki-regional-unit").
"""
import html as htmllib
import json
import re

from scraper.common import clean, fetch

MAX_PAGES = 30


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_row(row):
    details = {d.get("type"): d.get("value") for d in row.get("details") or []}
    sqm = _num(details.get("size"))
    if not sqm and row.get("type") in ("Οικόπεδο", "Αγροτεμάχιο"):
        sqm = _num(details.get("plot_size"))
    city = clean((row.get("city") or {}).get("name") or "")
    unit = clean((row.get("area") or {}).get("name") or "")
    if unit and unit != city:
        area, city = city, unit       # "Επανομή", "Θεσσαλονίκη" -> area Επανομή, city Θεσσαλονίκη
    else:
        area = ""
    beds = _num(details.get("bedrooms"))
    image = (row.get("featured_image") or {}).get("url")
    return {
        "source_id": str(row["id"]),
        "code": str(row["id"]),
        "url": row.get("detail_url") or f"https://elxis.com/gr/properties/{row['slug']}",
        "title": clean(row.get("name") or ""),
        "type": {"Σπίτι": "Μονοκατοικία"}.get(clean(row.get("type") or ""), clean(row.get("type") or "")) or None,
        "deal": "sale",
        "price": int(float(row["price"])) if row.get("price") else None,
        "sqm": sqm,
        "bedrooms": int(beds) if beds else None,
        "city": city,
        "area": area,
        "location": ", ".join(p for p in (area, city) if p),
        "available_from": None,
        "image": image,
        "description": clean(row.get("excerpt") or "")[:300],
        "_published": row.get("published_at") or "",
        "_gone": bool(row.get("sold_at")) or row.get("is_available") is False,
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    slug = site.get("area_slug", "thessaloniki-regional-unit")
    listings = {}
    complete = False
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/gr/area/{slug}", params={"page": page})
        m = re.search(r'data-page="([^"]*)"', html)
        if not m:
            break
        props = json.loads(htmllib.unescape(m.group(1))).get("props", {})
        block = props.get("properties") or {}
        rows = block.get("data") or []
        new_on_page = 0
        for row in rows:
            try:
                item = parse_row(row)
            except Exception as e:
                print(f"  [{site['id']}] skipped listing {row.get('id')}: {e}")
                continue
            if item["source_id"] not in listings:
                listings[item["source_id"]] = item
                new_on_page += 1
        last = (block.get("meta") or {}).get("last_page") or 1
        if new_on_page == 0 or page >= last:
            complete = True
            break
    items = [i for i in listings.values() if not i.pop("_gone")]
    items.sort(key=lambda i: i.pop("_published"), reverse=True)
    for rank, item in enumerate(items, 1):
        item["site_rank"] = rank
    return items, complete
