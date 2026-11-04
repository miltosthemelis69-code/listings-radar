"""Adapter for elgrekorealestate.com (El Greko Real Estate, Thessaloniki; Yii2 site).

Sales are server-rendered at /gr/property/sale/?page=N (24 div.thumbnail cards per page,
default order newest first). Cards link to /gr/property/show/<id>/ and give a title
("Διαμέρισμα 62 m² , Θεσσαλονίκη" = type, size, place), a short text ("… – Αγία Τριάδα."),
price, size / plot size / bedrooms icons and lazy background images.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

MAX_PAGES = 200


def parse_card(card, base_url):
    link = card.select_one(".tb18 a")
    href = link["href"]
    pid = re.search(r"/show/(\d+)", href).group(1)
    title = clean(link.get_text())
    m = re.match(r"(.+?)\s+[\d.,]+\s*m²\s*,\s*(.+)", title)
    if m:
        ptype, city = clean(m.group(1)), clean(m.group(2))
    else:
        ptype, _, city = (clean(x) for x in title.partition(","))
    place = [clean(x) for x in city.split(",") if clean(x)]  # "Κασσάνδρα, Χαλκιδική"
    city, sub = (place[-1].rstrip(". "), ", ".join(place[:-1])) if place else ("", "")
    text = clean(card.select_one(".text_box").get_text(" ")) if card.select_one(".text_box") else ""
    area = ""
    am = re.search(r"–\s*([^–]+?)\.?$", text)
    if am and "πωλ" not in am.group(1).lower():
        area = clean(am.group(1).split(",")[0])
    if area and (area == city or area.startswith(city) or city.startswith(area)):
        area = ""
    area = ", ".join(x for x in [area, sub] if x)
    sqm = beds = None
    for icon in card.select(".icon-item"):
        val = clean(icon.get_text(" "))
        src = icon.select_one("img")["src"] if icon.select_one("img") else ""
        if val.endswith("τμ") and sqm is None:
            sqm = parse_sqm(val)
        elif "υπνοδωμ" in val or "bed" in src:
            beds = parse_int(val)
    price = card.select_one(".item-price")
    bg = card.select_one(".product-carousel [data-background]")
    return {
        "source_id": pid,
        "code": pid,
        "url": urljoin(base_url + "/", href),
        "title": title,
        "type": ptype or None,
        "deal": deal_from_text(text) or "sale",
        "price": parse_price(price.get_text().replace(" ", "")) if price else None,
        "sqm": sqm,
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", bg["data-background"].split("?")[0]) if bg else None,
        "description": text[:300],
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings, complete = {}, True
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/gr/property/sale/", params={"page": page} if page > 1 else None)
        cards = [c for c in BeautifulSoup(html, "html.parser").select("div.thumbnail") if c.select_one(".tb18 a")]
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
