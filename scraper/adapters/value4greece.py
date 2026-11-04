"""Adapter for value4greece.com (custom WordPress theme).

Sales are listed at /status/polisi/page/N/ as a.rental-box cards (the theme calls
every listing a "rental", sales included). Card title: "Ιωάννινα, Αμπελόκηποι | Διαμέρισμα 80 τ.μ.".
"""
import re

from bs4 import BeautifulSoup

from scraper.common import clean, fetch, parse_int, parse_price, parse_sqm

MAX_PAGES = 100


def parse_card(card):
    url = card["href"]
    title = clean(card.select_one(".box-title").get_text()) if card.select_one(".box-title") else ""
    place, _, what = title.partition("|")
    parts = [clean(p) for p in place.split(",") if clean(p)]
    city, area = (parts[0], ", ".join(parts[1:])) if parts else ("", "")

    sqm = beds = None
    for span in card.select(".top-info .right-col span"):
        text = clean(span.get_text())
        if re.search(r"\bm\s*2|τ\.?μ", text):
            sqm = parse_sqm(text)
        elif text.startswith(("Υπνοδωμάτια", "Δωμάτια")):
            beds = parse_int(text)  # theme only shows "rooms", the closest thing to bedrooms here
    style = (card.select_one(".box-feat") or {}).get("style", "")
    img = re.search(r"url\('([^']+)'\)", style)
    price = card.select_one(".box-price")
    category = card.select_one(".subtitle")

    return {
        "source_id": url.rstrip("/").rsplit("/", 1)[-1],
        "code": None,
        "url": url,
        "title": clean(what) or title,
        "type": clean(re.split(r"\d", what, maxsplit=1)[0]) or None,
        "deal": "sale",
        "price": parse_price(price.get_text()) if price else None,
        "sqm": sqm,
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": img.group(1) if img else None,
        "description": clean(category.get_text()).strip("{}") if category else "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        url = f"{base_url}/status/polisi/" + (f"page/{page}/" if page > 1 else "")
        soup = BeautifulSoup(fetch(url), "html.parser")
        new_on_page = 0
        for card in soup.select("a.rental-box"):
            if not card.select_one(".box-title"):
                continue
            try:
                item = parse_card(card)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0 or not soup.select_one(f'a[href$="/status/polisi/page/{page + 1}/"]'):
            break
    return list(listings.values()), True
