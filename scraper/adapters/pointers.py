"""Adapter for pointers.gr (custom PHP site, Pointers Property Services, Thessaloniki).

Sales: /results.php?filter_int_to[]=1&orderby=1&page=N (orderby 1 = newest first), 12
.property-item cards a page; the page states the total ("124 ακίνητα"). A card has
.category, .sqm ("26000.00㎡"), .purpose ("Προς πώληση"), .code ("Κωδικός: 62-4505"),
.location spans (area, municipality), .price ("1.400.000€") and a background-image photo.
Bedrooms are not on the cards.
"""
import re
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_price, parse_sqm

MAX_PAGES = 60
SOLD = ("πωληθηκε", "πουληθηκε", "sold", "ενοικιαστηκε", "rented")


def parse_card(card, base_url):
    link = card.select_one("a[href*='property/']")
    href = link["href"]
    pid = re.search(r"property/(\d+)", href).group(1)
    text = lambda sel: clean(card.select_one(sel).get_text()) if card.select_one(sel) else ""
    spans = [clean(s.get_text()) for s in card.select(".location span") if clean(s.get_text())]
    area = spans[0] if spans else ""
    city = spans[-1] if len(spans) > 1 else area
    if area == city:
        area = ""
    style = (card.select_one(".image") or {}).get("style", "")
    img = re.search(r"url\('?([^')]+)'?\)", style)
    sqm_text = text(".sqm").replace("㎡", "")
    category, purpose = text(".category"), text(".purpose")
    return {
        "source_id": pid,
        "code": text(".code").replace("Κωδικός:", "").strip() or pid,
        "url": urljoin(base_url + "/", quote(href, safe="/:%")),
        "title": " ".join(p for p in (category, purpose.lower(), area or city) if p),
        "type": category or None,
        "deal": deal_from_text(purpose),
        "price": parse_price(text(".price")),
        "sqm": float(sqm_text) if re.fullmatch(r"\d+(\.\d+)?", sqm_text) else parse_sqm(sqm_text),
        "bedrooms": None,
        "city": city,
        "area": area,
        "location": ", ".join(p for p in (area, city) if p),
        "available_from": None,
        "image": img.group(1) if img else None,
        "description": "",
        "_sold": any(s in card.get_text(" ").lower() for s in SOLD),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    total = None
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/results.php", params={"filter_int_to[]": 1, "orderby": 1, "page": page})
        m = re.search(r"(\d+)\s*ακίνητα", html)
        if m:
            total = int(m.group(1))
        new_on_page = 0
        for card in BeautifulSoup(html, "html.parser").select(".property-item"):
            try:
                item = parse_card(card, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] not in listings:
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0 or (total and len(listings) >= total):
            break
    items = [i for i in listings.values() if not i.pop("_sold")]
    for rank, item in enumerate(items, 1):
        item["site_rank"] = rank
    return items, True
