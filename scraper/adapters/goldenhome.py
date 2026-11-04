"""Adapter for goldenhome.gr (Golden Home, a Greece-wide network; Yii2 site).

Sales are server-rendered at /property/pwlisi?params=/<area slug>&sort=-CreateTime&page=N
(30 article.property-card per page, newest first; "Εμφανίζονται 1-30 από 877").
The network has no per-store listing page, so `area_params` in the config limits the
scan to the area of the Thessaloniki store (default "/perioxi-thessaloniki-center",
the site's own "ΘΕΣΣΑΛΟΝΙΚΗ - ΚΕΝΤΡΟ" area). Cards give the id, title
("Διαμέρισμα 52τ.μ. προς πώληση"), area ("ΘΕΣΣΑΛΟΝΙΚΗ - ΚΕΝΤΡΟ - ΜΑΡΤΙΟΥ"),
bedrooms, size and price. Detail pages are /property/view/<id>.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

MAX_PAGES = 100


def text(card, sel):
    el = card.select_one(sel)
    return clean(el.get_text()) if el else ""


def parse_card(card, base_url):
    pid = card["data-key"]
    title = text(card, ".property-title")
    parts = [clean(p) for p in text(card, ".property-area").split(" - ") if clean(p)]
    city = parts[0].title() if parts else ""
    if city.upper() == "ΘΕΣΣΑΛΟΝΙΚΗ":
        city = "Θεσσαλονίκη"
    area = ", ".join(p for p in parts[1:] if p.upper() not in ("ΚΕΝΤΡΟ",)) or ("ΚΕΝΤΡΟ" if len(parts) > 1 else "")
    img = card.select_one(".property-image img")
    ptype = re.split(r"\s\d", title, maxsplit=1)[0].replace("Πώληση ", "")
    return {
        "source_id": pid,
        "code": text(card, ".property-id .id") or pid,
        "url": f"{base_url}/property/view/{pid}",
        "title": title,
        "type": ptype or None,
        "deal": deal_from_text(title) or "sale",
        "price": parse_price(text(card, ".property-price")),
        "sqm": parse_sqm(text(card, ".sm-area")) if text(card, ".sm-area") else None,
        "bedrooms": parse_int(text(card, ".rooms")) if text(card, ".rooms") else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    area_params = site.get("area_params", "/perioxi-thessaloniki-center")
    listings, complete = {}, True
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/property/pwlisi",
                     params={"params": area_params, "sort": "-CreateTime", "page": page, "per-page": 30})
        cards = BeautifulSoup(html, "html.parser").select("article.property-card[data-key]")
        new_on_page = 0
        for card in cards:
            try:
                item = parse_card(card, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0:
            break
    else:
        complete = False
    return list(listings.values()), complete
