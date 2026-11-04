"""Adapter for WordPress sites using the RealHomes theme (ellasestate.com,
thessaloniki-realestate.gr, thessrealestate.gr).

Newer RealHomes versions expose listings through the WP REST API
(/wp-json/wp/v2/property) with price, size, bedrooms and code in `property_meta` and
status / type / city as taxonomy term ids. The taxonomies' REST names differ between
versions ("property-status" vs "property-statuses"), so they are looked up first.
Multilingual sites return every language; when several statuses mean "for sale"
the Greek one is used, so each property comes once.

Older RealHomes versions keep listings out of the API; then set `list_path` to the
"for sale" status archive (e.g. "katastasi-akinitou/polisi/") and the cards there are read.
Site config: optional `list_path`, `city` (default city for the HTML mode),
`status_ids` (explicit sale status term ids).
"""
import html
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from scraper.adapters.wptools import (
    api_get, euro, greek_type, is_sold, load_terms, most_specific, place_from_terms, place_name, taxonomies_for, text_of)
from scraper.common import clean, deal_from_text, fetch, parse_int, parse_sqm, split_place

PER_PAGE = 100
GREEK = re.compile(r"[α-ωά-ώ]", re.I)


def meta(p, key):
    value = (p.get("property_meta") or {}).get(key)
    return value[0] if isinstance(value, list) and value else value


def scrape(site, known_ids=None):
    if site.get("list_path"):
        return scrape_archive(site)
    api = site["base_url"].rstrip("/") + "/wp-json/wp/v2"
    tax = taxonomies_for(api, "property")
    terms = {key: load_terms(api, tax[key]) if key in tax else {}
             for key in ("property-status", "property-type", "property-city")}

    statuses = terms["property-status"]
    sold_ids = {i for i, t in statuses.items() if is_sold(t["name"])}
    sale_ids = site.get("status_ids") or [
        i for i, t in statuses.items() if deal_from_text(t["name"]) == "sale" and i not in sold_ids]
    if len(sale_ids) > 1 and any(GREEK.search(statuses[i]["name"]) for i in sale_ids):
        sale_ids = [i for i in sale_ids if GREEK.search(statuses[i]["name"])]

    params = {"per_page": PER_PAGE, "orderby": "date", "order": "desc", "_embed": "wp:featuredmedia"}
    if sale_ids:
        params[tax["property-status"]] = ",".join(map(str, sale_ids))

    listings, page = [], 1
    while True:
        data = api_get(f"{api}/property", **params, page=page)
        for p in data:
            status = p.get(tax.get("property-status"), [])
            if sold_ids & set(status):
                continue
            try:
                item = parse_property(p, tax, terms)
            except Exception as e:
                print(f"  [{site['id']}] skipped property {p.get('id')}: {e}")
                continue
            item["site_rank"] = len(listings) + 1
            listings.append(item)
        if len(data) < PER_PAGE:
            break
        page += 1
    return listings, True


def parse_property(p, tax, terms):
    ids = lambda key: p.get(tax.get(key), []) if key in tax else []
    title = clean(html.unescape(p["title"]["rendered"]))
    city, area = place_from_terms(ids("property-city"), terms["property-city"])
    if not city:
        city, area = split_place(meta(p, "REAL_HOMES_property_address") or "")  # "Kassandra, Halkidiki"
        city, area = place_name(city), ("" if re.search(r"\d", area) else place_name(area))  # not a street
    statuses = [terms["property-status"][i]["name"] for i in ids("property-status") if i in terms["property-status"]]
    media = (p.get("_embedded") or {}).get("wp:featuredmedia") or [{}]
    excerpt = re.sub(r"<[^>]+>", " ", html.unescape((p.get("excerpt") or {}).get("rendered", "")))
    return {
        "source_id": str(p["id"]),
        "code": clean(str(meta(p, "REAL_HOMES_property_id") or p["id"])),
        "url": p["link"],
        "title": title,
        "type": ", ".join(greek_type(n) for n in most_specific(ids("property-type"), terms["property-type"])) or None,
        "deal": deal_from_text(" ".join(statuses)) or deal_from_text(title),
        "price": euro(f"{meta(p, 'REAL_HOMES_property_price') or ''} €"),
        "sqm": parse_sqm(meta(p, "REAL_HOMES_property_size") or ""),
        "bedrooms": parse_int(meta(p, "REAL_HOMES_property_bedrooms") or ""),
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "listed_at": p.get("date"),
        "image": media[0].get("source_url") or gallery_image(p),
        "description": clean(excerpt)[:300],
    }


def gallery_image(p):
    """First gallery image when the post has no featured image."""
    first = meta(p, "REAL_HOMES_property_images")
    if isinstance(first, dict) and first.get("file"):
        u = urlparse(p["link"])
        return f"{u.scheme}://{u.netloc}/wp-content/uploads/{first['file']}"
    return None


def scrape_archive(site):
    """Older RealHomes: cards on the "for sale" status archive, 10 per page."""
    base = site["base_url"].rstrip("/") + "/" + site["list_path"].lstrip("/")
    listings, seen = [], set()
    for page in range(1, 300):
        soup = BeautifulSoup(fetch(base + (f"page/{page}/" if page > 1 else "")), "html.parser")
        cards = soup.select("article.property-item")
        new = 0
        for card in cards:
            item = parse_card(card, site)
            if not item or item["source_id"] in seen:
                continue
            seen.add(item["source_id"])
            new += 1
            item["site_rank"] = len(listings) + 1
            listings.append(item)
        if not new or not soup.select_one(f'.pagination a[href$="/page/{page + 1}/"]'):
            break
    return listings, True


def parse_card(card, site):
    link = card.select_one("h4 a")
    if not link:
        return None
    title = text_of(link)
    status = text_of(card.select_one("figcaption"))
    if is_sold(status, title):
        return None
    meta_spans = [text_of(s) for s in card.select(".property-meta span")]
    code = next((re.sub(r"^Κωδ\.?\s*", "", s) for s in meta_spans if s.startswith("Κωδ")), "")
    sqm = next((parse_sqm(s) for s in meta_spans if "τ.μ" in s or "m²" in s), None)
    beds = next((parse_int(s) for s in meta_spans if re.search(r"Δωμάτ|Υπνοδ|Bed", s)), None)
    price_box = card.select_one(".price")
    small = price_box.select_one("small") if price_box else None
    broad_type = clean(text_of(small).lstrip("- ")) if small else ""
    # "Μεζονέτα 101τμ – Καλαμαριά": type first, place after the dash
    parts = re.split(r"\s+[–-]\s+", title, maxsplit=1)
    area = clean(parts[1]) if len(parts) > 1 else ""
    kind = re.sub(r"\s*\d.*$", "", parts[0]).strip() or broad_type
    img = card.select_one("figure img")
    url = link["href"]
    return {
        "source_id": url.rstrip("/").rsplit("/", 1)[-1],  # codes are not unique on every site
        "code": code,
        "url": url,
        "title": title,
        "type": kind or None,
        "deal": deal_from_text(status) or "sale",
        "price": euro(text_of(price_box).split(" - ")[0]),
        "sqm": sqm,
        "bedrooms": beds,
        "city": site.get("city", ""),
        "area": area,
        "location": ", ".join(x for x in [area, site.get("city", "")] if x),
        "available_from": None,
        "image": img.get("src") if img else None,
        "description": text_of(card.select_one(".detail p"))[:300],
    }
