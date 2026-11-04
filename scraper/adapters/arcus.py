"""Adapter for arcusrealestate.gr (Next.js app router, Arcus CRM).

The server-rendered search page /el/properties?reason=Προς Πώληση&page=N embeds the
listings in the React Server Components payload (self.__next_f.push chunks) as a
"properties":[{property_base_id, square_meters, price, type, region, municipality,
geographic_ids, ...}] array, 24 per page, newest first. The detail page is
/el/properties/<id> where id = 100000 + property_base_id (checked against the page's links).
Arcus also has Athens offices; `regions` in the site config (e.g. ["Θεσσαλονίκη"])
keeps only listings whose region matches.
"""
import json
import re

from scraper.common import clean, fetch, normalize

MAX_PAGES = 100
CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)


def rsc_payload(html):
    return "".join(json.loads('"' + c + '"') for c in CHUNK_RE.findall(html))


def properties_array(raw):
    """Pull the "properties":[...] JSON array out of the RSC text."""
    start = raw.find('"properties":[{"property_base_id"')
    if start < 0:
        return []
    start = raw.index("[", start)
    arr, _ = json.JSONDecoder().raw_decode(raw[start:])
    return arr


def parse_property(p, base_url, link_ids):
    base = p["property_base_id"]
    pid = base + 100000
    if link_ids and pid not in link_ids:
        pid = base  # fall back; the mapping is checked per page in scrape()
    geo = p.get("geographic_ids") or {}
    city = clean(p.get("municipality")) or clean(p.get("region"))
    area_parts = [clean(geo.get("name_gr"))]
    if geo.get("parent_name_gr") and normalize(geo["parent_name_gr"]) != normalize(city):
        area_parts.append(clean(geo["parent_name_gr"]))
    area = ", ".join(a for a in area_parts if a and normalize(a) != normalize(city))
    ptype = clean(p.get("type")) or clean(p.get("category"))
    if normalize(ptype) == "στουντιο":
        ptype = "Studio"  # the runner knows "studio", not the Greek spelling
    sqm = p.get("square_meters")
    price = p.get("price")
    return {
        "source_id": str(base),
        "code": str(pid),
        "url": f"{base_url}/el/properties/{pid}",
        "title": f"{ptype}, {sqm}τ.μ." if sqm else ptype,
        "type": ptype or None,
        "deal": "sale" if "πωλ" in normalize(p.get("reason")) else ("rent" if "ενοικ" in normalize(p.get("reason")) else None),
        "price": int(price) if price and price > 1 else None,
        "sqm": float(sqm) if sqm else None,
        "bedrooms": p.get("bedrooms") or None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": p.get("image") or None,
        "description": clean(p.get("address")),
        "_region": clean(p.get("region")),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    regions = {normalize(r) for r in site.get("regions", [])}
    listings, complete = {}, True
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/el/properties", params={"reason": "Προς Πώληση", "page": page})
        props = properties_array(rsc_payload(html))
        link_ids = {int(x) for x in re.findall(r'"/el/properties/(\d+)"', html)}
        new_on_page = 0
        for p in props:
            try:
                item = parse_property(p, base_url, link_ids)
            except Exception as e:
                print(f"  [{site['id']}] skipped property on page {page}: {e}")
                continue
            region = item.pop("_region")
            if item["source_id"] in listings:
                continue
            listings[item["source_id"]] = item
            new_on_page += 1
            item["_keep"] = not regions or normalize(region) in regions
        if new_on_page == 0:
            break
    else:
        complete = False
    kept = [i for i in listings.values() if i.pop("_keep")]
    for rank, item in enumerate(kept, 1):
        item["site_rank"] = rank
    return kept, complete
