"""Adapter for the newer realstatus.gr template (e.g. 38400.gr, RE/MAX Premier).

The listings page loads its results from /listings_async/page/N as an HTML fragment
of .card blocks (12 per page). The sale/rent filter can't be set by URL, so every
page is read and the runner drops rentals using the card's ΠΩΛΗΣΗ/ΕΝΟΙΚΙΑΣΗ label.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

MAX_PAGES = 100


def parse_card(card, base_url=None):
    link = card.select_one("a.prop-link")
    source_id = re.search(r"/property/(\d+)", link["href"]).group(1)
    title = clean(card.select_one(".card-body h2").get_text()) if card.select_one(".card-body h2") else ""
    label = card.select_one(".labels .label")
    place = card.select_one(".card-body > span")
    # "Ν. Ιωαννίνων, Ιωάννινα, Κέντρο" -> prefecture, city, area
    parts = [clean(p) for p in (place.get_text() if place else "").split(",") if clean(p)]
    parts = [p for p in parts if not p.startswith("Ν.")]
    city = parts[0] if parts else ""
    area = ", ".join(parts[1:])

    sqm = beds = None
    for li in card.select(".listing-icons li"):
        icon = " ".join(li.select_one("i").get("class", [])) if li.select_one("i") else ""
        text = clean(li.get_text())
        # templates differ: ruler or object-group icon, or just a "τ.μ" value
        if "ruler" in icon or "object-group" in icon or re.search(r"\d\s*(τ\.?\s?μ|m²|sq)", text):
            sqm = sqm or parse_sqm(text)
        elif "bed" in icon:
            beds = parse_int(text)
    code = card.select_one(".prop-id")
    img = card.select_one("img.listing-img")
    if not img:  # some templates set the photo as the card's background
        bg = re.search(r"url\(['\"]?([^'\")]+)", (card.select_one(".card-img") or {}).get("style", "") or "")
        img = {"src": bg.group(1)} if bg else None
    price = card.select_one(".proprice") or card.select_one(".listing-price .price-p span")

    # "ΠΩΛΕΙΤΑΙ ΔΙΑΜΕΡΙΣΜΑ 87 ΤΜ ..." -> "ΔΙΑΜΕΡΙΣΜΑ"
    words = re.sub(r"^(ΠΩΛΕΙΤΑΙ|ΠΩΛΟΥΝΤΑΙ|ΕΝΟΙΚΙΑΖΕΤΑΙ|ΕΝΟΙΚΙΑΖΟΝΤΑΙ)\s+", "", title, flags=re.I)
    prop_type = clean(re.split(r"\d", words, maxsplit=1)[0]).capitalize() or None

    return {
        "source_id": source_id,
        "code": clean(code.get_text()).replace("Κωδ.", "").strip() if code else source_id,
        "url": urljoin(base_url + "/", link["href"]) if base_url else link["href"],  # some templates link relatively
        "title": title.capitalize(),
        "type": prop_type,
        "deal": deal_from_text(f"{label.get_text() if label else ''} {title}"),
        "price": parse_price(price.get_text()) if price else None,
        "sqm": sqm,
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": img.get("src") if img else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        cards = BeautifulSoup(fetch(f"{base_url}/listings_async/page/{page}"), "html.parser").select(".card")
        new_on_page = 0
        for card in cards:
            if not card.select_one("a.prop-link"):
                continue
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
    return list(listings.values()), True
