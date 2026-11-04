"""Adapter for WordPress sites using the Realtyna WPL plugin (e.g. oikiarealestate.gr).

Listings are server-rendered on /properties/ as .wpl_prp_cont cards. We request
100 per page sorted newest-added first. The site keeps rented/sold listings online
with a tag, so those are dropped. WPL servers can be slow (~25s per page), so the
adapter supports an incremental mode that stops at the first page with nothing new.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, fetch, normalize, parse_int, parse_price, parse_sqm

PAGE_SIZE = 100
MAX_PAGES = 100
UNAVAILABLE_TAGS = ("ενοικιαστηκε", "πουληθηκε", "πωληθηκε", "μη διαθεσιμο")


def split_type(title):
    """'Διαμέρισμα Προς Ενοικίαση' / 'Οικόπεδο Πωλείται' -> property type."""
    return clean(re.split(r"\s+(?:προς|πωλείται|πωλειται|ενοικιάζεται|ενοικιαζεται|ενοικίαση|ενοικιαση|πώληση|πωληση)\b", title, maxsplit=1, flags=re.I)[0]) or None


def split_location(location):
    """'Χατζή Πελλερέν, Ιωάννινα' / 'Ανατολή- Ιωάννινα' -> (city, area)."""
    parts = [p.strip() for p in re.split(r",|-\s+", location) if p.strip()]
    if not parts:
        return "", ""
    return parts[-1], ", ".join(parts[:-1])


def parse_card(card, base_url):
    source_id = card["id"].replace("wpl_prp_cont", "")
    link = card.select_one("a.view_detail")
    title = clean(card.select_one(".wpl_prp_title").get_text())  # "Διαμέρισμα Προς Ενοικίαση"
    tags = [clean(t.get_text()) for t in card.select(".wpl-listing-tag")]

    lower = normalize(title)
    deal = "rent" if ("ενοικ" in lower or "μισθ" in lower) else "sale" if "πωλ" in lower else None
    prop_type = split_type(title)

    location = clean(card.select_one(".wpl_prp_listing_location").get_text()) if card.select_one(".wpl_prp_listing_location") else ""
    city, area = split_location(location)

    area_el = card.select_one(".wpl_prp_listing_icon_box [class*=area]")
    beds = card.select_one(".wpl_prp_listing_icon_box .bedroom .value")
    img = card.select_one("img.wpl_gallery_image")
    desc = card.select_one(".wpl_prp_desc")
    price = card.select_one(".price_box")

    return {
        "source_id": source_id,
        "code": source_id,
        "url": link["href"] if link else None,
        "title": title,
        "type": prop_type,
        "deal": deal,
        "price": parse_price(price.get_text()) if price else None,
        "sqm": parse_sqm(area_el.get_text()) if area_el else None,
        "bedrooms": parse_int(beds.get_text()) if beds else None,
        "city": city,
        "area": area,
        "location": location,
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": clean(desc.get_text()) if desc else "",
        "tags": tags,
        "_available": not any(normalize(t) in UNAVAILABLE_TAGS for t in tags),
    }


def scrape(site, known_ids=None):
    """Return (listings, complete). complete=False when we stopped early (incremental)."""
    base_url = site["base_url"].rstrip("/")
    list_url = urljoin(base_url + "/", site.get("list_path", "properties/"))
    listings, seen = {}, set()
    for page in range(1, MAX_PAGES + 1):
        html = fetch(list_url, params={"limit": PAGE_SIZE, "wplpage": page, "wplorderby": "p.add_date",
                                       "wplorder": "DESC", **site.get("params", {})})
        cards = BeautifulSoup(html, "html.parser").select(".wpl_prp_cont[id^=wpl_prp_cont]")
        page_ids, fresh = set(), 0
        for card in cards:
            try:
                item = parse_card(card, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            page_ids.add(item["source_id"])
            if not item.pop("_available"):
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                if known_ids is not None and item["source_id"] not in known_ids:
                    fresh += 1
        if not cards or page_ids <= seen:  # past the last page
            return list(listings.values()), True
        seen |= page_ids
        if known_ids is not None and fresh == 0:  # newest-first: nothing new from here on
            return list(listings.values()), False
    return list(listings.values()), True
