"""Adapter for WordPress sites using the MyHome theme (e.g. housecity.gr).

MyHome serves its listings as JSON from POST /wp-json/myhome/v1/estates with
attributes (offer type, subcategory, city, neighbourhood, size, bedrooms). There is
no price field: agents write it in the title ("... Τιμή πώλησης 220.000 €").
"""
import json
import re

import requests

from scraper.common import USER_AGENT, clean, deal_from_text, parse_int, parse_price, parse_sqm, normalize

PER_PAGE = 100
# "220.000 €", "154.999€", "210.000 ευρώ", "160.000 Eυρώ" (Latin E), "(65.000 ευρώ)"
PRICE_RE = re.compile(r"(\d{1,3}(?:[.\s]\d{3})+|\d{4,})(?:,\d+)?\s*(?:€|[εΕeE]υρ[ωώ])", re.I)


def attr(estate, slug):
    return [clean(v["name"]) for a in estate["attributes"] if a["slug"] == slug for v in a["values"]]


def parse_estate(e):
    title = clean(e["name"])
    offer = attr(e, "offer-type")
    price = PRICE_RE.search(title) or PRICE_RE.search(e.get("excerpt") or "")
    subtypes = attr(e, "subcategories")
    size = attr(e, "property-size")
    beds = attr(e, "bedrooms")
    city = (attr(e, "poli") or [""])[0]
    area = (attr(e, "neighborhood") or [""])[0]
    if normalize(area).startswith(normalize(city)):  # "Ιωάννινα (κέντρο)"
        area = clean(area[len(city):].strip(" ()")).capitalize()
    return {
        "source_id": str(e["id"]),
        "code": str(e["id"]),
        "url": e["link"],
        "title": title,
        "type": subtypes[-1] if subtypes else (attr(e, "property-type") or [None])[0],
        "deal": deal_from_text(" ".join(offer)) if offer else deal_from_text(title),
        "price": parse_price(price.group(1)) if price else None,
        "sqm": parse_sqm(size[0]) if size else (parse_sqm(title) if re.search(r"\d\s*τ\.?\s*μ", title) else None),
        "bedrooms": parse_int(beds[0]) if beds else None,
        "city": city,
        "area": area.title() if area.isupper() else area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": e.get("image"),
        "description": clean(e.get("excerpt") or ""),
    }


def scrape(site, known_ids=None):
    url = site["base_url"].rstrip("/") + "/wp-json/myhome/v1/estates"
    listings, page = [], 1
    while True:
        r = requests.post(url, json={"limit": PER_PAGE, "page": page},
                          headers={"User-Agent": USER_AGENT}, timeout=60)
        r.raise_for_status()
        data = r.json()
        for e in data["results"]:
            try:
                item = parse_estate(e)
            except Exception as ex:
                print(f"  [{site['id']}] skipped estate {e.get('id')}: {ex}")
                continue
            item["site_rank"] = len(listings) + 1
            listings.append(item)
        if len(data["results"]) < PER_PAGE or len(listings) >= int(data.get("found_results") or 0):
            return listings, True
        page += 1
