"""Adapter for the newer estateplus.gr site theme (dehome.gr).

Unlike the theme `estateplus.py` reads (.kf_listing_outer_wrap cards on
/listings?listingType=for+sale, a filter this theme ignores), these sites print every
matching listing as one JSON array in the page's map script: showmapListings([...]).
/el/buy lists sales only, so one request reads everything.

The array is sorted by price, so `site_rank` follows the listing id (higher = newer).
Location reads "Area, Sub-area, Θεσσαλονίκη - Δήμος" or "Area, Municipality,
Θεσσαλονίκη - Περιφ/κοί δήμοι"; for the latter the municipality becomes the city.
"""
import json
import re
from urllib.parse import urljoin

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

SOLD = ("πουλήθηκε", "πωλήθηκε", "sold")


def place_of(location):
    parts = [clean(p) for p in (location or "").split(",") if clean(p)]
    if not parts:
        return "", ""
    last = parts[-1]
    if re.search(r"Περιφ", last) and len(parts) > 1:  # "Καλαμαριά, Θεσσαλονίκη - Περιφ/κοί δήμοι"
        return parts[-2], ", ".join(parts[:-2])
    city = clean(re.sub(r"\s*-\s*Δήμος\s*$", "", last))  # "Θεσσαλονίκη - Δήμος" -> "Θεσσαλονίκη"
    return city, ", ".join(parts[:-1])


def parse_row(row, base_url):
    city, area = place_of(row.get("location"))
    prop_type = clean(row.get("propertyType")) or None
    size = row.get("size")
    title = f"{prop_type or 'Ακίνητο'} {size} τ.μ." if size else (prop_type or "")
    photos = row.get("photos") or []
    desc = clean(row.get("descriptionGR") or "")
    return {
        "source_id": str(row["id"]),
        "code": str(row["id"]),
        "url": urljoin(base_url + "/", row["url"]),
        "title": title,
        "type": prop_type,
        "deal": deal_from_text(f"{row.get('type') or ''} {row.get('listing_type') or ''}"),
        "price": parse_price(row.get("price")) if row.get("price") else None,
        "sqm": parse_sqm(str(size)) if size else None,
        "bedrooms": parse_int(str(row["rooms"])) if row.get("rooms") else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": photos[0] if photos else None,
        "description": desc[:300],
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    html = fetch(f"{base_url}/{site.get('list_path', 'el/buy').lstrip('/')}")
    start = html.find("showmapListings(")
    if start < 0:
        raise RuntimeError("no showmapListings data on the listings page")
    rows, _ = json.JSONDecoder().raw_decode(html[start + len("showmapListings("):])
    listings = {}
    for row in sorted(rows, key=lambda r: -int(r["id"])):  # newest (highest id) first
        if any(s in clean(row.get("descriptionGR") or "").lower()[:80] for s in SOLD):
            continue
        try:
            item = parse_row(row, base_url)
        except Exception as e:
            print(f"  [{site['id']}] skipped listing {row.get('id')}: {e}")
            continue
        if item["source_id"] not in listings:
            item["site_rank"] = len(listings) + 1
            listings[item["source_id"]] = item
    return list(listings.values()), True
