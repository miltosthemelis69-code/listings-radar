"""Adapter for agency sites built by wapp.gr (e.g. elite-realestate.gr).

Listings are server-rendered on /properties/page:N as .estate_box cards, newest
first. The card title carries the CRM code: "2673813 - Οικόπεδο Προς Πώληση, ...".
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm, split_place

MAX_PAGES = 100


def parse_card(box, base_url):
    href = box.select_one("a.overlay_link")["href"]
    m = re.search(r"/(\d+)-(\d+)-[^/]*$", href)
    title = clean(box.select_one(".estate-title").get_text()) if box.select_one(".estate-title") else ""
    name = re.sub(r"^\d+\s*-\s*", "", title)  # "Οικόπεδο Προς Πώληση, Ιωάννινα, 581 τ.μ., €65.000"

    sqm = beds = None
    for info in box.select(".estate-info"):
        icon = (info.select_one("img") or {}).get("src", "")
        if "m2" in icon:
            sqm = parse_sqm(info.get_text())
        elif "bed" in icon or "room" in icon:
            beds = parse_int(info.get_text())

    location = clean(box.select_one(".estate-address").get_text()) if box.select_one(".estate-address") else ""
    city, area = split_place(location)
    label = box.select_one(".estate-img p")
    img = box.select_one(".estate-img img")
    price = box.select_one(".price")

    return {
        "source_id": m.group(2) if m else href,
        "code": m.group(2) if m else None,
        "url": urljoin(base_url + "/", href),
        "title": name,
        "type": clean(re.split(r"\s+προς\s+", name, maxsplit=1, flags=re.I)[0]) or None,
        "deal": deal_from_text(f"{label.get_text() if label else ''} {name}"),
        "price": parse_price(price.get_text()) if price else None,
        "sqm": sqm,
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": location,
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        url = f"{base_url}/properties" + (f"/page:{page}" if page > 1 else "")
        soup = BeautifulSoup(fetch(url), "html.parser")
        boxes = soup.select(".estate_box")
        new_on_page = 0
        for box in boxes:
            try:
                item = parse_card(box, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        # the server errors (500) past the last page, so follow the pager instead of probing
        if new_on_page == 0 or not soup.select_one(f'a[href$="/properties/page:{page + 1}"]'):
            break
    return list(listings.values()), True
