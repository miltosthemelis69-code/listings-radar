"""Adapter for WordPress sites using the Houzez theme (e.g. ioanninacasa.gr).

Houzez exposes listings as JSON through the WP REST API (/wp-json/wp/v2/properties)
with price/size in `property_meta` and status/type/city as taxonomy ids, which we
resolve to names once per run. Only the "for sale" status is requested.
Older Houzez versions (e.g. mesitikogeorgiou.gr) leave `property_meta` out of the API;
then price/size come from the cards on the "for sale" status pages.
"""
import html
import json
import re

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

PER_PAGE = 100


def load_terms(api, taxonomy):
    terms, page = {}, 1
    while True:
        data = json.loads(fetch(f"{api}/{taxonomy}", params={"per_page": 100, "page": page, "_fields": "id,name"}))
        terms.update({t["id"]: html.unescape(t["name"]) for t in data})
        if len(data) < 100:
            return terms
        page += 1


def meta(p, key):
    value = (p.get("property_meta") or {}).get(key)
    return value[0] if isinstance(value, list) and value else value


def parse_property(p, terms):
    title = clean(html.unescape(p["title"]["rendered"]))  # "2680815 – Διαμέρισμα Προς Πώληση, Ιωάννινα, 70 τ.μ., €150.000"
    code = re.match(r"(\d+)\s*[–-]", title)
    names = lambda tax: [terms[tax][i] for i in p.get(tax, []) if i in terms[tax]]

    # city terms read "Ιωάννινα / Κέντρο" (city first, unlike the other sites)
    city_parts = [clean(x) for x in " / ".join(names("property_city")).split("/") if clean(x)]
    city = city_parts[0] if city_parts else ""
    area = ", ".join(names("property_area")) or ", ".join(city_parts[1:])
    media = (p.get("_embedded") or {}).get("wp:featuredmedia") or [{}]
    excerpt = re.sub(r"<[^>]+>", " ", html.unescape((p.get("excerpt") or {}).get("rendered", "")))

    return {
        "source_id": str(p["id"]),
        "code": code.group(1) if code else str(p["id"]),
        "url": p["link"],
        "title": re.sub(r"^\d+\s*[–-]\s*", "", title),
        "type": ", ".join(names("property_type")) or None,
        "deal": deal_from_text(" ".join(names("property_status"))),
        "price": parse_price(meta(p, "fave_property_price")),
        "sqm": parse_sqm(meta(p, "fave_property_size")),
        "bedrooms": parse_int(meta(p, "fave_property_bedrooms") or ""),
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "listed_at": p.get("date"),
        "image": media[0].get("source_url"),
        "description": clean(excerpt),
    }


def scrape(site, known_ids=None):
    api = site["base_url"].rstrip("/") + "/wp-json/wp/v2"
    terms = {tax: load_terms(api, tax) for tax in ("property_status", "property_type", "property_city", "property_area")}
    sale_ids = [i for i, name in terms["property_status"].items() if deal_from_text(name) == "sale"]
    params = {"per_page": PER_PAGE, "orderby": "date", "order": "desc", "_embed": "wp:featuredmedia"}
    if sale_ids:
        params["property_status"] = ",".join(map(str, sale_ids))

    listings, page = [], 1
    while True:
        data = json.loads(fetch(f"{api}/properties", params={**params, "page": page}))
        for p in data:
            try:
                item = parse_property(p, terms)
            except Exception as e:
                print(f"  [{site['id']}] skipped property {p.get('id')}: {e}")
                continue
            item["site_rank"] = len(listings) + 1
            listings.append(item)
        if len(data) < PER_PAGE:
            break
        page += 1

    # older Houzez versions don't put price/size in the API; read them off the status pages instead
    if listings and all(i["price"] is None and i["sqm"] is None for i in listings):
        fill_from_status_pages(api, sale_ids, listings)
    return listings, True


def fill_from_status_pages(api, status_ids, listings):
    by_id = {i["source_id"]: i for i in listings}
    for status_id in status_ids:
        url = json.loads(fetch(f"{api}/property_status/{status_id}", params={"_fields": "link"}))["link"]
        for page in range(1, 200):
            soup = BeautifulSoup(fetch(url + (f"page/{page}/" if page > 1 else "")), "html.parser")
            cards = soup.select(".item-wrap[id^=ID-]")
            for card in cards:
                item = by_id.get(card["id"].removeprefix("ID-"))
                if not item:
                    continue
                price, area, beds = (card.select_one(s) for s in (".item-price", ".h-area", ".h-beds"))
                item["price"] = parse_price(price.get_text()) if price else None
                item["sqm"] = parse_sqm(area.get_text()) if area else None
                item["bedrooms"] = parse_int(beds.get_text()) if beds else item["bedrooms"]
            if not cards or not soup.select_one(f'a[href$="/page/{page + 1}/"]'):
                break
