"""Adapter for grekodom.com (ASP.NET MVC site, Greece-wide listings in English).

Search results are server-rendered at /RealtyObjects?multiRegion=<ids>&aim=1&sortFilter=1&page=N
(aim=1 = for sale, sortFilter=1 = date created, newest first; 15 .listing-item cards per
page; header "<span class=js-fav-total>1376</span> properties"). `regions` in the config
limits the search to the site's Thessaloniki regions (4 = Thessaloniki,
22 = Thessaloniki/suburbs). Cards give title ("Flat 70 m² in Thessaloniki"), price,
Code, Sq. Meters and Rooms.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.adapters.ktimatoemporiki import greek_type
from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

MAX_PAGES = 200


def place(text):
    """'in the suburbs of Thessaloniki' -> ('Θεσσαλονίκη', 'Προάστια'); 'in Asprovalta' -> ('Asprovalta', '')."""
    t = re.sub(r"^in\s+", "", clean(text))
    if t.lower() == "thessaloniki":
        return "Θεσσαλονίκη", ""
    if "suburbs of thessaloniki" in t.lower():
        return "Θεσσαλονίκη", "Προάστια"
    return t, ""


def parse_card(card, base_url):
    link = card.select_one(".listing-title h4 a")
    title = clean(link.get_text())
    feats = {clean(li.contents[0]) if li.contents else "": clean(li.select_one("span").get_text())
             for li in card.select(".listing-features li") if li.select_one("span")}
    badges = clean(card.select_one(".listing-badges").get_text()) if card.select_one(".listing-badges") else ""
    price_el = card.select_one(".listing-price")
    price_text = ""
    if price_el:
        for extra in price_el.select("i, del"):
            extra.extract()
        price_text = price_el.get_text()
    addr = card.select_one(".listing-address")
    city, area = place(addr.get_text() if addr else "")
    img = card.select_one(".listing-carousel img")
    code = feats.get("Code") or re.search(r"/realtyobject/(\d+)", link["href"]).group(1)
    ptype = re.split(r"\s\d", title, maxsplit=1)[0]
    return {
        "source_id": code,
        "code": code,
        "url": urljoin(base_url + "/", link["href"]),
        "title": title,
        "type": greek_type(ptype) or ptype,
        "deal": deal_from_text(badges) or "sale",
        "price": parse_price(price_text.replace(",", "")),
        "sqm": parse_sqm(feats.get("Sq. Meters", "").replace(",", "")) if feats.get("Sq. Meters") else None,
        "bedrooms": parse_int(feats.get("Rooms")) if feats.get("Rooms") else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": img["src"] if img and img.get("src") else None,
        "description": "",
        "_sold": "sold" in badges.lower(),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    regions = ",".join(str(r) for r in site.get("regions", [4, 22]))
    listings, complete = {}, True
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/RealtyObjects",
                     params={"multiRegion": regions, "aim": 1, "IsCyprus": "false", "sortFilter": 1, "page": page})
        cards = BeautifulSoup(html, "html.parser").select(".listing-item")
        new_on_page = 0
        for card in cards:
            try:
                item = parse_card(card, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] in listings:
                continue
            listings[item["source_id"]] = item
            new_on_page += 1
        if new_on_page == 0:
            break
    else:
        complete = False
    items = [i for i in listings.values() if not i.pop("_sold")]
    for rank, item in enumerate(items, 1):
        item["site_rank"] = rank
    return items, complete
