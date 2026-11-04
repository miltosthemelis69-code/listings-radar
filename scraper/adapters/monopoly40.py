"""Adapter for monopoly40.com (Monopoly Home, custom PHP site).

Sales are listed at /listing-list.php?prop_ad_type=1&page=N (1 = sale, 2 = rent), 9
`.list-offer` cards per page, newest first. The card title holds everything:
"#14369: Γκαρσονιερα για ΠΩΛΗΣΗ στην περιοχή: Άγιος Δημήτριος | 53 τ.μ, Τιμή: € 130000".
The detail URL id (estate-details.php?id=14484) differs from the agency code (#14369).
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

MAX_PAGES = 200
SOLD_WORDS = ("πουληθ", "πωληθηκε", "ενοικιαστηκε", "sold")


def parse_card(card, base_url):
    link = card.select_one("a.list-offer-right[href*='estate-details.php']")
    href = link["href"]
    source_id = re.search(r"id=(\d+)", href).group(1)
    title_el = card.select_one(".list-offer-title")
    title = clean(title_el.get_text(" "))
    code_el = title_el.select_one("strong")
    code = clean(code_el.get_text()).strip("#:") if code_el else source_id
    head = clean(title.replace(code_el.get_text(), "", 1)) if code_el else title
    m = re.match(r"(.+?)\s+για\s+(\S+)\s+στην περιοχή:\s*([^|]*)", head)
    est_type = clean(card.select_one(".estate-type").get_text()) if card.select_one(".estate-type") else None
    deal_text = clean(card.select_one(".transaction-type").get_text()) if card.select_one(".transaction-type") else ""
    place = ""
    if m:
        est_type = est_type or clean(m.group(1))
        deal_text = deal_text or m.group(2)
        place = clean(m.group(3))
    area_el = card.select_one(".list-area")
    rooms_el = card.select_one(".list-rooms")
    price_el = card.select_one(".list-price")
    img = card.select_one(".list-offer-photo img")
    desc = card.select_one(".list-offer-text p")
    sqm = parse_sqm(area_el.get_text()) if area_el else None
    return {
        "source_id": source_id,
        "code": code,
        "url": urljoin(base_url + "/", href),
        "title": head.split("|")[0].strip() or title,
        "type": est_type,
        "deal": deal_from_text(deal_text),
        "price": parse_price(price_el.get_text()) if price_el else None,
        "sqm": sqm or None,
        "bedrooms": parse_int(rooms_el.get_text()) or None if rooms_el else None,
        "city": place,
        "area": "",
        "location": place,
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": clean(desc.get_text(" "))[:300] if desc else "",
        "_flags": normalize(title + " " + deal_text),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/listing-list.php", params={"prop_ad_type": 1, "page": page})
        soup = BeautifulSoup(html, "html.parser")
        cards = [c for c in soup.select(".list-offer")
                 if c.select_one("a.list-offer-right[href*='estate-details.php']")]
        new_on_page = 0
        for card in cards:
            try:
                item = parse_card(card, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            flags = item.pop("_flags")
            if item["source_id"] in listings or any(w in flags for w in SOLD_WORDS):
                continue
            item["site_rank"] = len(listings) + 1
            listings[item["source_id"]] = item
            new_on_page += 1
        if new_on_page == 0:
            break
    return list(listings.values()), True
