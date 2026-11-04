"""Adapter for remax-gold.gr (RE/MAX Gold, Thessaloniki; custom PHP front end over estateplus CRM).

Sales are server-rendered per category at /el/buy/Greece/<category>?page=N
(categories residential, commercial, land, other; 12 .box-dream cards per page, newest
first; "Αναζήτηση 755 αποτελέσματα"). Cards link to /el/property/<agent>-<id> and give
title ("Διαμέρισμα 80τμ"), price, location ("Βυζάντιο, Καλαμαριά, Θεσσαλονίκη - Περιφ.
Δήμοι"), bedrooms ("2 Υ/Δ") and size.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

CATEGORIES = ["residential", "commercial", "land", "other"]
MAX_PAGES = 150


def split_location(text):
    """'<area>, <municipality>, Θεσσαλονίκη - Περιφ. Δήμοι' -> (municipality, area);
    '<area>, Θεσσαλονίκη - Κέντρο' -> ('Θεσσαλονίκη', area)."""
    parts = list(dict.fromkeys(clean(p) for p in (text or "").split(",") if clean(p)))
    if not parts:
        return "", ""
    zone, rest = parts[-1], parts[:-1]
    if rest and re.search(r"Περιφ|Υπόλ|Υπολ", zone):
        return rest[-1], ", ".join(rest[:-1])
    return zone.split(" - ")[0], ", ".join(rest)


def parse_card(card, base_url):
    link = card.select_one(".content .title a")
    href = link["href"]
    title = clean(link.get_text())
    loc = card.select_one(".location p")
    city, area = split_location(loc.get_text() if loc else "")
    beds = sqm = None
    for item in card.select(".icon-box .item"):
        icon = item.select_one("i")
        val = clean(item.get_text())
        cls = " ".join(icon.get("class", [])) if icon else ""
        if "flaticon-hotel" in cls:
            beds = parse_int(val)
        elif "flaticon-minus-front" in cls:
            sqm = parse_sqm(val)
    tags = " ".join(clean(t.get_text()) for t in card.select(".list-tags .tags-item"))
    img = card.select_one(".image img")
    price = card.select_one(".content .price")
    pid = href.rstrip("/").rsplit("/", 1)[-1]
    return {
        "source_id": pid,
        "code": pid,
        "url": urljoin(base_url + "/", href),
        "title": title,
        "type": clean(re.split(r"\s\d", title, maxsplit=1)[0]) or None,
        "deal": deal_from_text(tags) or "sale",
        "price": parse_price(price.get_text()) if price else None,
        "sqm": sqm,
        "bedrooms": beds or None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": img["src"] if img and img.get("src") else None,
        "description": "",
        "_sold": bool(re.search(r"πουλήθηκε|πωλήθηκε|sold", tags, re.I)),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings, complete = {}, True
    for cat in site.get("categories", CATEGORIES):
        for page in range(1, MAX_PAGES + 1):
            html = fetch(f"{base_url}/el/buy/Greece/{cat}", params={"page": page} if page > 1 else None)
            cards = BeautifulSoup(html, "html.parser").select(".box-dream")
            new_on_page = 0
            for card in cards:
                if not card.select_one(".content .title a"):
                    continue
                try:
                    item = parse_card(card, base_url)
                except Exception as e:
                    print(f"  [{site['id']}] skipped card on {cat} page {page}: {e}")
                    continue
                if "${" in item["url"] or item["source_id"] in listings:
                    continue
                listings[item["source_id"]] = item
                new_on_page += 1
            if new_on_page == 0:
                break
        else:
            complete = False
    # several category scans: newest first = highest property number first
    num = lambda i: int(re.sub(r"\D", "", i["source_id"].split("-")[-1]) or 0)
    items = sorted((i for i in listings.values() if not i.pop("_sold")), key=lambda i: -num(i))
    for rank, item in enumerate(items, 1):
        item["site_rank"] = rank
    return items, complete
