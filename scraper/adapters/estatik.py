"""Adapter for WordPress sites using the Estatik real estate plugin (gaiarealty.gr).

Estatik keeps its properties out of the REST API, so listings are read from the cards
on the "for sale" listings page (`list_path`, e.g. "el/akinita/pros-polisi/"): title,
price, bedrooms, area, address, deal and category terms. Pagination uses the plugin's
own "?paged-N=" links, followed until there is no next link.
"""
import re

from bs4 import BeautifulSoup

from scraper.adapters.wptools import euro, is_sold, place_name, text_of
from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_sqm

MAX_PAGES = 100


# Greek addresses spell out the spitogatos-style place: "Χαριλάου (Θεσσαλονίκη - Δήμος) Δημοχάρους, ..."
PLACE_PAREN = re.compile(r"([^,()]+?)\s*\(([^()-]+?)\s*-\s*([^()]+)\)")


def parse_address(text):
    """'Karabournaki, Kalamaria Municipality 551 31, Greece' -> ('Καλαμαριά', 'Karabournaki');
    'Κέντρο, Χαριλάου (Θεσσαλονίκη - Δήμος) Δημοχάρους, 7' -> ('Θεσσαλονίκη', 'Χαριλάου')."""
    text = re.sub(r"\s*\b(Greece|Ελλάδα)\b", "", text)
    m = PLACE_PAREN.search(text)
    if m:
        place, region, kind = (clean(g) for g in m.groups())
        if "δημος" in normalize(kind) and "δημοι" not in normalize(kind):  # "(Θεσσαλονίκη - Δήμος)": area of the city
            return place_name(region), place
        return place_name(place), ""  # "(Θεσσαλονίκη - Περιφ/κοί δήμοι)": the place is a municipality
    parts = [clean(re.sub(r"\b\d{3}\s?\d{2}\b", "", p)) for p in text.split(",")]
    parts = [p for p in parts if p and not p.isdigit()]
    if not parts:
        return "", ""
    return place_name(parts[-1]), ", ".join(parts[:-1])


def parse_card(card, base):
    link = card.select_one(".es-listing__title a")
    if not link:
        return None
    title = text_of(link)
    terms = [text_of(a) for a in card.select(".es-listing__terms a")]
    labels = " ".join(text_of(x) for x in card.select(".es-label, .es-badge, .es-listing__labels"))
    if is_sold(labels, title):
        return None
    deal = next((deal_from_text(t) for t in terms if deal_from_text(t)), None) or deal_from_text(title)
    city, area = parse_address(text_of(card.select_one(".es-address")))
    img = card.select_one("img[data-lazy], img[src]")
    num = lambda sel: text_of(card.select_one(f"{sel} b"))
    return {
        "source_id": card["data-post-id"],
        "code": card["data-post-id"],
        "url": link["href"],
        "title": title,
        "type": clean(title.split(",")[0]) or None,  # "Διαμέρισμα, 84τ.μ."
        "deal": deal,
        "price": euro(text_of(card.select_one(".es-price"))),
        "sqm": parse_sqm(num(".es-listing__meta-area")) or (parse_sqm(title) if re.search(r"\d\s*(τ\.?μ|m²)", title) else None),
        "bedrooms": parse_int(num(".es-listing__meta-bedrooms")),
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": (img.get("data-lazy") or img.get("src")) if img else None,
        "description": text_of(card.select_one(".es-listing__excerpt, .es-listing__content__excerpt"))[:300],
    }


def scrape(site, known_ids=None):
    base = site["base_url"].rstrip("/")
    url = f"{base}/{site['list_path'].lstrip('/')}"
    listings, seen = [], set()
    for _ in range(MAX_PAGES):
        soup = BeautifulSoup(fetch(url), "html.parser")
        new = 0
        for card in soup.select(".es-listing[data-post-id]"):
            if card["data-post-id"] in seen:
                continue
            seen.add(card["data-post-id"])
            new += 1
            item = parse_card(card, base)
            if item:
                item["site_rank"] = len(listings) + 1
                listings.append(item)
        nxt = soup.select_one(".es-pagination a.next")
        if not new or not nxt:
            break
        url = nxt["href"]
    return listings, True
