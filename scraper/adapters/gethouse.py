"""Adapter for agency sites on the gethouse.gr / re1.gr platform.

Both share a backend (/property/<id>/<slug>, /image/N/thumb/...) but use different
templates, so each card style has its own parser:
  - gethouse.gr: /properties/sales?page=N, <article class="property">
  - re1.gr:      /pwliseis?location=102&page=N, <div class="property">
site["list_path"] and site["params"] pick the listing page (e.g. location=102 = Ν. Ιωαννίνων).
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

MAX_PAGES = 200


def _base(href, base_url):
    return re.search(r"/property/(\d+)", href).group(1), urljoin(base_url + "/", href)


def parse_article(card, base_url):
    """gethouse.gr template."""
    link = card.select_one("h2 a")
    source_id, url = _base(link["href"], base_url)
    title = clean(link.get_text()).rstrip(".")  # "Α.Μ.1706 Διαμέρισμα Δυάρι"
    code = price = sqm = None
    for label in card.select(".attr .label"):
        text = clean(label.get_text())
        if text.startswith("Κωδικός"):
            code = text.split(":", 1)[-1].strip()
        elif "€" in text:
            price = parse_price(text)
        elif "μ" in text:
            sqm = parse_sqm(text)
    # "Διαμέρισμα δυάρι > Νομός Δήμος Ιωαννίνων > Δήμος Ιωάννινα > ΑΡΧ. ΜΑΚΑΡΙΟΥ"
    path_el = card.select_one(".attr .hide-for-small-only")
    parts = [clean(p) for p in path_el.get_text("|").split("|") if clean(p)] if path_el else []
    city = re.sub(r"^Δήμος\s+", "", parts[2]) if len(parts) > 2 else ""
    area = ", ".join(parts[3:])
    img = card.select_one("img")
    return {
        "source_id": source_id, "code": code or source_id, "url": url,
        "title": re.sub(r"^Α\.Μ\.\s*\d+\s*", "", title),
        "type": parts[0] if parts else None,
        "deal": deal_from_text(title + " " + url) or "sale",
        "price": price, "sqm": sqm, "bedrooms": None,
        "city": city, "area": area.title() if area.isupper() else area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": "",
    }


def parse_div(card, base_url):
    """re1.gr template."""
    link = card.select_one("a.image")
    source_id, url = _base(link["href"], base_url)
    bottom = card.select_one(".image-bottom")
    beds = None
    for attr in card.select(".attributes .attribute"):
        if "Υπνοδωμάτια" in attr.get_text():
            beds = parse_int(attr.select_one("div").get_text())
    # "Ιωάννινα / Δήμος Ιωαννίνων / Ιωάννινα" -> prefecture / municipality / area
    loc = [clean(p) for p in card.select_one(".location").get_text().split("/")] if card.select_one(".location") else []
    city = re.sub(r"^Δήμος\s+", "", loc[1]) if len(loc) > 1 else (loc[0] if loc else "")
    area = loc[2] if len(loc) > 2 and loc[2] != loc[0] else ""
    code = card.select_one(".content-footer div")
    img = card.select_one("a.image img")
    title = clean(card.select_one("h2.title").get_text()) if card.select_one("h2.title") else ""
    return {
        "source_id": source_id,
        "code": clean(code.get_text()).lstrip("#").strip() if code else source_id,
        "url": url, "title": title,
        "type": clean(card.select_one(".image-top .type").get_text()) if card.select_one(".image-top .type") else None,
        "deal": deal_from_text(card.select_one(".image-top .scope").get_text() if card.select_one(".image-top .scope") else title),
        "price": parse_price(card.select_one(".price").get_text()) if card.select_one(".price") else None,
        "sqm": parse_sqm(bottom.select_one("div").get_text()) if bottom and bottom.select_one("div") else None,
        "bedrooms": beds,
        "city": city, "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    list_url = urljoin(base_url + "/", site.get("list_path", "properties/sales"))
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(fetch(list_url, params={**site.get("params", {}), "page": page}), "html.parser")
        cards = [(c, parse_article) for c in soup.select("article.property")] + \
                [(c, parse_div) for c in soup.select("div.property") if c.select_one("a.image")]
        new_on_page = 0
        for card, parse in cards:
            try:
                item = parse(card, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0:
            break
    return list(listings.values()), True
