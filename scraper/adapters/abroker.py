"""Adapter for agency sites built on the abroker.gr platform (Astro front end, images on
abroker-app S3): mesitiki.net, monopoly.com.gr, katikia.com.gr, thermaikosrealest.gr,
aki-nito.gr, eliteps.gr.

Sales are listed at /el/properties?type=2&limit=50&page=N (type 1 = rent, 2 = buy), sorted by
the site's default (last update, newest first). Two card templates exist: `article.card`
(most sites) and `article.tile` (eliteps.gr); both carry title "Type, 85τ.μ.", an area line
"Municipality - Area", price, "#code" and a bed-icon feature for bedrooms.
"""
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

MAX_PAGES = 100
PAGE_SIZE = 50
SOLD_WORDS = ("πουληθ", "πωληθηκε", "ενοικιαστηκε", "sold", "rented")


def fix_encoding(html):
    """The server sends no charset, so requests decodes the UTF-8 pages as Latin-1."""
    try:
        return html.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return html


def parse_card(card, base_url):
    link = card.select_one("h3 a[href]")
    href = link["href"]
    title = clean(link.get_text())
    type_part, _, size_part = title.rpartition(",")
    if not type_part:
        type_part, size_part = title, ""
    place = clean((card.select_one(".area") or {}).get_text() if card.select_one(".area") else "")
    parts = [clean(p) for p in place.split(" - ") if clean(p)]
    # "Θεσσαλονίκη - Δήμος - Χαριλάου" -> city Θεσσαλονίκη, area Χαριλάου
    parts = [p for p in parts if normalize(p) != "δημος"]
    city = parts[0] if parts else ""
    area = ", ".join(parts[1:]) if len(parts) > 1 else ""
    code_el = card.select_one(".code")
    code = clean(code_el.get_text()).lstrip("#") if code_el else href.rstrip("/").rsplit("/", 1)[-1]
    price_el = card.select_one(".facts strong") or card.select_one(".price")
    badge = card.select_one(".badge.type") or card.select_one(".chips")
    beds = None
    for li in card.select("ul.features li"):
        svg = li.select_one("svg path")
        if svg and svg.get("d", "").startswith("M2 4v16"):  # lucide "bed" icon
            beds = parse_int(li.get_text())
    img = card.select_one("img")
    image = None
    if img:
        image = img.get("src") or img.get("data-fallback")
    desc = card.select_one(".text")
    badge_text = clean(badge.get_text()) if badge else ""
    deal = deal_from_text(badge_text)
    if deal is None and "αγορ" in normalize(badge_text):
        deal = "sale"
    return {
        "source_id": code,
        "code": code,
        "url": urljoin(base_url + "/", href),
        "title": title,
        "type": clean(type_part) or None,
        "deal": deal,
        "price": parse_price(price_el.get_text()) if price_el else None,
        "sqm": parse_sqm(size_part) if "τ.μ" in size_part else None,
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", image) if image else None,
        "description": clean(desc.get_text())[:300] if desc else "",
        "_flags": normalize(" ".join(clean(b.get_text()) for b in card.select(".badge, .chips, .over"))),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    lang = site.get("lang", "el")
    listings = {}
    complete = False
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/{lang}/properties",
                     params={"type": 2, "limit": PAGE_SIZE, "page": page})
        soup = BeautifulSoup(fix_encoding(html), "html.parser")
        cards = [a for a in soup.select("article") if a.select_one("h3 a[href*='/property/']")]
        new_on_page = 0
        for card in cards:
            try:
                item = parse_card(card, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            flags = item.pop("_flags")
            if item["source_id"] in listings:
                continue
            if any(w in flags for w in SOLD_WORDS):
                continue
            item["site_rank"] = len(listings) + 1
            listings[item["source_id"]] = item
            new_on_page += 1
        if new_on_page == 0 or len(cards) < PAGE_SIZE:
            complete = True
            break
    return list(listings.values()), complete
