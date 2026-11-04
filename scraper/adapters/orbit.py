"""Adapter for agency sites on the orbit.gr platform (e.g. realhouses.gr).

/properties/listing_lines?page=N&pageSize=S lists .list-item.property cards. The
search filter lives in the server session and doesn't stick reliably, so we fetch
everything in large pages and keep cards whose *visible* status tag says for sale
(each card carries both tags, one hidden with display:none).
"""
import re
from urllib.parse import urljoin, quote

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

PAGE_SIZE = 500
MAX_PAGES = 20


def visible(el):
    return el is not None and "display:none" not in (el.get("style") or "").replace(" ", "")


def field(card, label):
    for dt in card.select("dl dt"):
        if clean(dt.get_text()).rstrip(":") == label and visible(dt):
            dd = dt.find_next_sibling("dd")
            return clean(dd.get_text()) if dd else None
    return None


def parse_card(card, base_url):
    link = card.select_one('a[href*="property_detail"]')
    source_id = re.search(r"property_detail/(\d+)", link["href"]).group(1)
    status = next((clean(f.get_text()) for f in card.select("figure.tag.status") if visible(f)), "")
    heading = card.select_one("header h3")
    kind = clean(heading.select_one("span").get_text()) if heading and heading.select_one("span") else ""
    area = clean(card.select_one("header figure").get_text()) if card.select_one("header figure") else ""
    price = card.select_one("p.property-price")
    desc = card.select_one("#description p.title")
    img = card.select_one(".property-image img")
    land = field(card, "Εμβαδόν οικοπέδου")
    description = re.sub(r",\s*τιμή.*$", "", clean(desc.get_text())) if desc else ""
    # cards only name the area; most are in Ioannina, but some are on the coast (Σύβοτα, Πάργα)
    city = "Ιωάννινα" if re.search(r"ιωανν|γιανν", normalize(description)) else ""
    return {
        "source_id": source_id,
        "code": source_id,
        "url": urljoin(base_url + "/", link["href"]),
        "title": re.sub(r"\bm 2\b", "m²", clean(heading.get_text(" "))) if heading else kind,
        "type": kind.capitalize() or None,
        "deal": deal_from_text(status),
        "price": parse_price(price.get_text()) if price else None,
        "sqm": parse_sqm(field(card, "Εμβαδόν") or land or ""),
        "bedrooms": parse_int(field(card, "Υπνοδωμάτια") or ""),
        "city": city,
        "area": area.title(),
        "location": ", ".join(x for x in [area.title(), city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", quote(img["src"])) if img and img.get("src") else None,
        "description": description,
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/properties/listing_lines", params={"page": page, "pageSize": PAGE_SIZE})
        cards = BeautifulSoup(html, "html.parser").select(".list-item.property")
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
        if new_on_page == 0 or len(cards) < PAGE_SIZE:
            break
    return list(listings.values()), True
