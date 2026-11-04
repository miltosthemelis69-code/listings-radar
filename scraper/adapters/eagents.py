"""Adapter for agency sites on the e-agents workspace platform (polisestate.gr, greekestate.eu,
oikies.net, lithosrealestate.gr, …).

The listings page loads its results from /{lang}/properties-list as an HTML fragment
(18 cards per page). We ask for newest-listed first (sorting=sendDateDesc) and
aim=1 (for sale) so rentals are never downloaded.

e-agents agencies pick from several card designs (geodir "article" cards with or without a
summary line, "pxp-results-card" overlays, "listing-style1" boxes), so cards are found from
their `properties/<id>` links and read from their text and icons rather than fixed classes.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import canonical_type, clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm, split_place

MAX_PAGES = 100
LINK = re.compile(r"properties/(\d+)")
PRICE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{3,})\s*(?:,\d+)?\s*€")
SQM = re.compile(r"(\d[\d.,]*)\s*(?:m\s*(?:²|2)\b|τ\.\s?μ\.?|τμ\b)")
# where each design puts the place name, most specific first
PLACE_SELECTORS = ["h3.title-sin_item span", "h6.list-title span", ".pxp-results-card-1-details-title > span:first-child",
                   ".geodir-category-content h3:not(.title-sin_item) span"]


def link_id(a):
    m = LINK.search(a.get("href", ""))
    return m.group(1) if m else None


def card_of(link):
    """Largest ancestor of the link that holds no other listing's link."""
    pid, node = link_id(link), link
    while node.parent is not None and node.parent.name != "[document]":
        others = {link_id(a) for a in node.parent.select('a[href*="properties/"]')} - {pid, None}
        if others:
            break
        node = node.parent
    return node


def parse_card(card, source_id, list_base):
    text = clean(card.get_text(" "))
    summary = card.select_one(".geodir-category-content .pb-5:not(.geodir-category-content_price)")
    summary_text = re.sub(r"\bm 2\b", "m²", clean(summary.get_text(" "))) if summary else ""

    place = []
    for sel in PLACE_SELECTORS:
        place = [clean(s.get_text()).strip(",| ") for s in card.select(sel) if clean(s.get_text()).strip(",| ")]
        if place:
            break
    location = ", ".join(place)
    city, area = split_place(location)

    beds = None
    bed_icon = card.select_one("i[class*=bed]")
    if bed_icon:
        after = bed_icon.find_parent("li") or bed_icon.parent
        beds = parse_int(after.get_text()) if after.name == "li" else parse_int(clean(bed_icon.next_sibling.get_text() if hasattr(bed_icon.next_sibling, "get_text") else str(bed_icon.next_sibling or "")) or clean(bed_icon.find_next(string=re.compile(r"\d")) or ""))
    if beds is None:
        m = re.search(r"(\d+)\s*Υπνοδωμάτι", text)
        beds = int(m.group(1)) if m else None

    price = PRICE.search(text)
    sqm = SQM.search(text)
    kind = canonical_type(summary_text, clean((card.select_one("h3.title-sin_item") or card).get_text(" ")), text)
    img = next((i.get("src") for i in card.select("img") if i.get("src") and "fav" not in i["src"] and "logo" not in i["src"]), None)
    if not img:
        bg = re.search(r"url\(['\"]?([^'\")]+)", str(card))
        img = bg.group(1) if bg else None
    aim = card.select_one(".aimbox, .list-tag span")

    return {
        "source_id": source_id,
        "code": source_id,
        "url": urljoin(list_base, f"properties/{source_id}"),
        "title": summary_text or " ".join(x for x in [kind, f"{sqm.group(1)} m²" if sqm else ""] if x),
        "type": kind,
        "deal": deal_from_text(f"{aim.get_text() if aim else ''} {summary_text} {text}"),
        "price": parse_price(price.group(1)) if price else None,
        "sqm": parse_sqm(sqm.group(1)) if sqm else None,
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": location,
        "available_from": None,
        "image": urljoin(list_base, img) if img else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    list_base = f"{site['base_url'].rstrip('/')}/{site.get('lang', 'el')}/"
    params = {"sorting": "sendDateDesc", **site.get("params", {})}
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(fetch(urljoin(list_base, "properties-list"), params={**params, "page": page}), "html.parser")
        seen_on_page, new_on_page = set(), 0
        for link in soup.select('a[href*="properties/"]'):
            pid = link_id(link)
            if not pid or pid in seen_on_page:
                continue
            seen_on_page.add(pid)
            try:
                item = parse_card(card_of(link), pid, list_base)
            except Exception as e:
                print(f"  [{site['id']}] skipped card {pid} on page {page}: {e}")
                continue
            if pid not in listings:
                item["site_rank"] = len(listings) + 1
                listings[pid] = item
                new_on_page += 1
        if new_on_page == 0:
            break
    return list(listings.values()), True
