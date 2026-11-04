"""Adapter for 2310realestate.gr (custom PHP site, listings served from ihome.2310realestate.gr).

Sales are split by category: /results_listing.php?mtype=<houses|commercials|lands|loipa>
&transaction1=1&start=N (1 = sale, 2 = rent; `start` is the page number, 10 cards per page,
newest first). The site needs a `slider-range-areaK-value` param for each category or it
returns nothing. Each page states its category total in <input id="hmany">. Sidebar
"featured" cards also link to estate_details_listing.php, so only #main_res cards are read.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

CATEGORIES = [("houses", 1), ("commercials", 2), ("lands", 3), ("loipa", 4)]
MAX_PAGES = 150
SOLD_WORDS = ("πουληθ", "πωληθηκε", "ενοικιαστηκε", "sold")


def fix_encoding(html):
    """The server sends no charset, so requests decodes the UTF-8 pages as Latin-1."""
    try:
        return html.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return html


def parse_card(card, base_url):
    link = card.select_one("a.list-offer-right[href*='dios_code=']")
    href = link["href"]
    code = re.search(r"dios_code=(\d+)", href).group(1)
    title = clean(card.select_one(".list-offer-title").get_text(" "))
    # "Διαμέρισμα 80 μ 2 προς πώληση"
    m = re.match(r"(.+?)\s+([\d.,]+)\s*μ", title)
    est_type = clean(m.group(1)) if m else clean(re.split(r"\s+προς\s+", title)[0])
    place = clean((card.select_one(".sub_h4") or BeautifulSoup("", "html.parser")).get_text()).strip("() ")
    parts = []
    for p in place.split(" - "):
        p = clean(p)
        if p and p not in parts:
            parts.append(p)
    city = parts[0] if parts else ""
    area = ", ".join(reversed(parts[1:]))
    area_el = card.select_one(".list-area")
    rooms_el = card.select_one(".list-rooms")
    price_el = card.select_one(".list-price")
    img = card.select_one(".list-offer-photo img")
    text_el = card.select_one(".list-offer-text")
    desc = clean(text_el.get_text(" ")) if text_el else ""
    desc = clean(desc.replace(title, "", 1).replace(card.select_one(".sub_h4").get_text(), "", 1)) \
        if card.select_one(".sub_h4") else desc
    return {
        "source_id": code,
        "code": code,
        "url": urljoin(base_url + "/", href),
        "title": re.sub(r"\s+2\s+προς", " προς", title).replace(" μ ", " μ² "),
        "type": est_type or None,
        "deal": deal_from_text(title),
        "price": parse_price(price_el.get_text()) if price_el else None,
        "sqm": (parse_sqm(area_el.get_text()) or None) if area_el else (parse_sqm(m.group(2)) if m else None),
        "bedrooms": (parse_int(rooms_el.get_text()) or None) if rooms_el else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": desc[:300],
        "_flags": normalize(title),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    complete = True
    for mtype, k in CATEGORIES:
        expected = None
        seen_here = 0
        for page in range(1, MAX_PAGES + 1):
            html = fetch(f"{base_url}/results_listing.php", params={
                "mtype": mtype, "start": page, "transaction1": 1, "apo": "", "eos": "",
                f"slider-range-area{k}-value": "0 - 100000000"})
            soup = BeautifulSoup(fix_encoding(html), "html.parser")
            hmany = soup.select_one("#hmany")
            if hmany and hmany.get("value", "").isdigit():
                expected = int(hmany["value"])
            main = soup.select_one("#main_res") or soup
            new_on_page = 0
            cards = main.select(".list-offer")
            for card in cards:
                if not card.select_one("a.list-offer-right[href*='dios_code=']"):
                    continue
                try:
                    item = parse_card(card, base_url)
                except Exception as e:
                    print(f"  [{site['id']}] skipped card ({mtype} p{page}): {e}")
                    continue
                flags = item.pop("_flags")
                if item["source_id"] in listings:
                    continue
                seen_here += 1
                if any(w in flags for w in SOLD_WORDS):
                    continue
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
            if new_on_page == 0 or (expected is not None and page * 10 >= expected):
                break
        if expected is not None and seen_here < expected * 0.95:
            print(f"  [{site['id']}] {mtype}: read {seen_here} of {expected}")
            complete = False
    return list(listings.values()), complete
