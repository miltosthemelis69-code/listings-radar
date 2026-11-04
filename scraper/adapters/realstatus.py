"""Adapter for agency sites built on the realstatus.gr CRM (e.g. gikaispiti.gr).

Listings are server-rendered on results.php?page=N as .property-list__item cards.
The site shows no publish date (the card's date is "available from"), so we request
orderby=1 (newest published first) and keep each listing's position as `site_rank`.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, fetch, parse_int, parse_price, parse_sqm

MAX_PAGES = 200


def parse_card(card, base_url):
    link = card.select_one(".title a")
    href = link["href"]
    source_id = re.search(r"id=(\d+)", href).group(1)
    title = clean(link.get_text())

    code_el = card.select_one(".title span")
    code = clean(code_el.get_text()).replace("Κωδ:", "").strip() if code_el else None

    # "Διαμέρισμα 70.00 τ.μ. προς πώληση"
    lower = title.lower()
    deal = "rent" if "ενοικ" in lower else "sale" if "πώλησ" in lower or "πωλησ" in lower else None
    prop_type = clean(re.split(r"\d", title, maxsplit=1)[0]) or None

    location = clean(card.select_one(".location").get_text()) if card.select_one(".location") else ""
    city, _, area = location.partition(",")

    date_el = card.select_one(".moment-ago")
    img = card.select_one(".image img")
    desc = card.select_one(".description")
    beds = card.select_one(".bedrooms-count")

    return {
        "source_id": source_id,
        "code": code,
        "url": urljoin(base_url + "/", href),
        "title": title,
        "type": prop_type,
        "deal": deal,
        "price": parse_price(card.select_one(".price").get_text()) if card.select_one(".price") else None,
        "sqm": parse_sqm(card.select_one(".sqm").get_text()) if card.select_one(".sqm") else None,
        "bedrooms": parse_int(beds.get_text()) if beds else None,
        "city": clean(city),
        "area": clean(area),
        "location": location,
        "available_from": date_el.get("data-value") if date_el else None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": clean(desc.get_text()) if desc else "",
    }


def scrape(site, known_ids=None):
    """Always a full scan: the site is fast (~40s for everything)."""
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/results.php",
                     params={"page": page, "orderby": 1, "locale": "el_GR", **site.get("params", {})})
        cards = BeautifulSoup(html, "html.parser").select(".property-list__item")
        new_on_page = 0
        for card in cards:
            try:
                item = parse_card(card, base_url)
            except Exception as e:  # one broken card shouldn't kill the run
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1  # 1 = most recently published
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0:  # past the last page (site repeats last page or returns empty)
            break
    return list(listings.values()), True
