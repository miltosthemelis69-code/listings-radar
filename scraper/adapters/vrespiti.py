"""Adapter for vrespiti.gr (custom ASP site).

Sales are listed at /search?purpose=1&p=N, 10 .divlink.rec cards per page, newest
edited first. Each card links to pdetails?id=<code>, e.g. "Κ-24067".
"""
import re
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm, split_place

MAX_PAGES = 300
UNAVAILABLE_LABELS = ("sold", "poulithike", "pwlithike", "rented")


def parse_card(card, base_url):
    href = card.select_one('a[href^="pdetails"]')["href"]
    code = unquote(re.search(r"id=([^&]+)", href).group(1))
    heading = clean(card.select_one("h3").get_text()) if card.select_one("h3") else ""  # "ΔΙΑΜΕΡΙΣΜΑ 35 τ.μ. προς Πώληση"
    place = clean(card.select_one("h4").get_text()) if card.select_one("h4") else ""  # "ΚΕΝΤΡΟ - ΙΩΑΝΝΙΝΑ, ΙΩΑΝΝΙΝΑ"
    city, area = split_place(place)
    area = clean(area.split(" - ")[0]) if area else ""

    sqm = beds = None
    for span in card.select(".infoline span"):
        icon = (span.select_one("img") or {}).get("src", "")
        if "sq" in icon:
            sqm = parse_sqm(span.get_text())
        elif "bed" in icon:
            beds = parse_int(span.get_text())
    img = card.select_one(".photo img")
    label = (card.select_one(".thelabel img") or {}).get("src", "")
    desc = card.select_one("p.ad")
    price = card.select_one("p.price")

    return {
        "source_id": code,
        "code": code,
        "url": f"{base_url}/pdetails?id={quote(code)}",
        "title": heading.capitalize(),
        "type": clean(re.split(r"\d", heading, maxsplit=1)[0]).capitalize() or None,
        "deal": deal_from_text(heading),
        "price": parse_price(price.get_text()) if price else None,
        "sqm": sqm,
        "bedrooms": beds,
        "city": city.title(),
        "area": area.title(),
        "location": ", ".join(x for x in [area.title(), city.title()] if x),
        "available_from": None,
        "image": f"{base_url}/{img['src'].lstrip('/')}" if img and img.get("src") else None,
        "description": clean(desc.get_text()).replace("Διαβάστε περισσότερα.", "").strip() if desc else "",
        "_available": not any(x in label.lower() for x in UNAVAILABLE_LABELS),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/search", params={"purpose": 1, "sortby": "EditedAt_Desc", "p": page})
        cards = BeautifulSoup(html, "html.parser").select(".divlink.rec")
        new_on_page = 0
        for card in cards:
            try:
                item = parse_card(card, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item.pop("_available") and item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        if not cards or new_on_page == 0:
            break
    return list(listings.values()), True
