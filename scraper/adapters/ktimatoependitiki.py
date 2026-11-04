"""Adapter for ktimatoependitiki.gr (REALTY - Κτηματοεπενδυτική; custom classic-ASP style site).

Sales are server-rendered at /search?lng=&purpose=1&p=N (purpose=1 = for sale, 12 cards
per page, "Ακίνητα 1 έως 12 από 2008"). Each card links to pdetails?...&id=<code>
(codes like "Β-35507", Greek letter prefix), with title "ΔΙΑΜΕΡΙΣΜΑ-ΚΕΝΤΡΟ ΘΕΣΣΑΛΟΝΙΚΗΣ
ΘΕΣΣΑΛΟΝΙΚΗ ΚΕΝΤΡΟ" (type-area zone), image alt "ΔΙΑΜΕΡΙΣΜΑ προς Πώληση - ΘΕΣΣΑΛΟΝΙΚΗ
ΚΕΝΤΡΟ", "3 Δωμάτια", "300 τ.μ." and the (possibly reduced) price.
"""
import re
from urllib.parse import parse_qs, quote, urljoin, urlparse

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

MAX_PAGES = 300


def parse_card(card, base_url):
    link = card.select_one("h3 a")
    href = link["href"]
    code = parse_qs(urlparse(href).query)["id"][0]
    title = clean(link.get_text())
    img = card.select_one(".photo img")
    alt = clean(img.get("alt")) if img else ""
    m = re.match(r"(.+?) προς (Πώληση|Ενοικίαση) - (.+)", alt)
    ptype, deal_word, zone = (m.group(1), m.group(2), m.group(3)) if m else (title.split("-")[0], "", "")
    area = title[len(ptype) + 1:] if title.startswith(ptype + "-") else ""
    if zone and area.endswith(" " + zone):
        area = area[: -len(zone) - 1]
    if normalize(zone).startswith("θεσσαλονικη"):
        city = "Θεσσαλονίκη"
        sub = clean(zone[len("ΘΕΣΣΑΛΟΝΙΚΗ"):])
        area = area or sub  # neighbourhood ("ΜΕΛΙΣΟΧΩΡΙ"), else the zone ("ΔΥΤΙΚΑ ΠΡΟΑΣΤΙΑ")
    elif zone:
        city = zone.title()
    else:  # no zone: "ΑΓΡΟΤΕΜΑΧΙΟ-ΚΕΝΤΡΙΚΗ ΕΛΛΑΔΑ"
        city, area = area.title(), ""
    if normalize(ptype) == "στουντιο":
        ptype = "Studio"
    specs = card.select_one("h4").get_text(" ") if card.select_one("h4") else ""
    rooms = re.search(r"(\d+)\s*Δωμάτια", specs)
    size = re.search(r"([\d.,]+)\s*τ\.μ\.", specs)
    price = card.select_one(".price-after") or card.select_one(".price")
    return {
        "source_id": code,
        "code": code,
        "url": urljoin(base_url + "/", f"pdetails?lng=&purpose=1&id={quote(code)}"),
        "title": title,
        "type": ptype or None,
        "deal": deal_from_text(deal_word) or "sale",
        "price": parse_price(price.get_text()) if price else None,
        "sqm": parse_sqm(size.group(1)) if size else None,
        "bedrooms": int(rooms.group(1)) if rooms else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings, complete = {}, True
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/search", params={"lng": "", "purpose": 1, "p": page})
        soup = BeautifulSoup(html, "html.parser")
        new_on_page = 0
        for card in soup.select("#searchresults .rec"):
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
