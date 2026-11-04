"""Adapter for WordPress sites using the Findeo theme with the Realteo plugin (agnrealestate.gr).

Realteo's REST output has no price, size or offer type, so listings are read from the
property archive cards (`list_path`, default "properties/?_offer_type=sale"): price,
address, badge ("Προς πώληση" / "Πωλήθηκε"), code, size and rooms. Paginated /page/N/.
"""
import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from scraper.adapters.wptools import euro, is_sold, text_of
from scraper.common import clean, deal_from_text, fetch, parse_int, parse_sqm, split_place

MAX_PAGES = 100


def page_url(url, page):
    if page == 1:
        return url
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=parts.path.rstrip("/") + f"/page/{page}/"))


def parse_card(card):
    link = card.select_one(".listing-title h4 a") or card.select_one("a.listing-img-container")
    if not link:
        return None
    badges = " ".join(text_of(b) for b in card.select(".property-badge"))
    title = clean(card.get("data-title") or text_of(link))
    if is_sold(badges):
        return None
    details = {li.get("class", [""])[0].removeprefix("main-detail-"): text_of(li.select_one("span"))
               for li in card.select(".listing-details li")}
    city, area = split_place(card.get("data-address") or "")
    post = card.select_one("[data-post_id]")
    url = link["href"]
    return {
        "source_id": post["data-post_id"] if post else url.rstrip("/").rsplit("/", 1)[-1],
        "code": details.get("_listing") or "",
        "url": url,
        "title": title,
        "type": clean(re.split(r"\s*,|\s+\d", title)[0]) or None,  # "Μεζονέτα, 250τ.μ."
        "deal": deal_from_text(badges),
        "price": euro(text_of(card.select_one(".listing-price"))),
        "sqm": parse_sqm(details.get("_area", "")) or (parse_sqm(title) if re.search(r"\d\s*τ\.?μ", title) else None),
        "bedrooms": parse_int(details.get("_bedrooms") or details.get("_rooms") or ""),
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": card.get("data-image"),
        "description": "",
    }


def scrape(site, known_ids=None):
    url = site["base_url"].rstrip("/") + "/" + site.get("list_path", "properties/?_offer_type=sale").lstrip("/")
    listings, seen = [], set()
    for page in range(1, MAX_PAGES):
        soup = BeautifulSoup(fetch(page_url(url, page)), "html.parser")
        new = 0
        for card in soup.select(".listing-item"):
            key = card.get("data-title", "") + str(card.select_one("a[href]") and card.select_one("a[href]")["href"])
            if key in seen:
                continue
            seen.add(key)
            new += 1
            item = parse_card(card)
            if not item:
                continue
            item["site_rank"] = len(listings) + 1
            listings.append(item)
        if not new or not soup.select_one(f'.pagination a[href*="/page/{page + 1}/"]'):
            break
    return listings, True
