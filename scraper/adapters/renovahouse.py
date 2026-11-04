"""Adapter for renovahouse.gr (custom Laravel site fed by its own PMS, pms.renovahouse.gr).

Sales are listed at /properties?status=1&page_size=50&page=N as <a href="/property/<id>"> cards
(.card) with a deal badge, price ("€33,000", comma thousands), size ("20 m²"), a category
label, a title and "Δήμος , Περιοχή". The header states the total ("42 Ακίνητα"). There is no
newest-first sort, so site_rank follows the numeric id, highest first. Bedrooms are not shown.

Cards only show the broad category ("Κατοικία"), so the specific type comes from re-querying
with subcategory_id[]=N (ids below, read from the detail pages in 2026-11); listings in a
subcategory not in the map keep the title-derived or broad type.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import CANONICAL_TYPES, canonical_type, clean, deal_from_text, fetch, parse_sqm

MAX_PAGES = 50
PAGE_SIZE = 50
SUBCATEGORIES = {6: "Διαμέρισμα", 7: "Γκαρσονιέρα", 8: "Μονοκατοικία", 9: "Βίλα", 10: "Οροφοδιαμέρισμα",
                 12: "Μεζονέτα", 13: "Studio", 24: "Κατάστημα"}
SOLD = ("πωληθηκε", "πουληθηκε", "sold", "ενοικιαστηκε", "rented")


def _type(title, label):
    """The card label is broad ("Κατοικία"); the title usually names the real type."""
    from_title = canonical_type(title)
    if from_title in {name for name, _ in CANONICAL_TYPES}:
        return from_title
    return label or None


def parse_card(a, base_url):
    href = urljoin(base_url + "/", a["href"])
    pid = re.search(r"/property/(\d+)", href).group(1)
    title = clean(a.select_one(".card-title").get_text()) if a.select_one(".card-title") else ""
    badges = [clean(b.get_text()) for b in a.select(".badge")]
    overlays = [clean(d.get_text()) for d in a.select(".position-absolute.text-white")]
    price = sqm = None
    for text in overlays:
        if "€" in text:
            digits = re.sub(r"[^\d]", "", text)
            price = int(digits) if digits else None
        elif "m²" in text or "τ.μ" in text:
            sqm = parse_sqm(text.replace(",", ""))
    place = clean(a.select_one("p.card-text").get_text()) if a.select_one("p.card-text") else ""
    parts = [clean(p) for p in place.split(",") if clean(p)]
    city = parts[0] if parts else ""
    area = ", ".join(parts[1:])
    img = a.select_one("img.card-img-top")
    label = a.select_one(".category-label")
    code = re.search(r"_(K-\d+)_", img["src"]) if img and img.get("src") else None
    return {
        "source_id": pid,
        "code": code.group(1) if code else pid,
        "url": href,
        "title": title,
        "type": _type(title, clean(label.get_text()) if label else ""),
        "deal": deal_from_text(" ".join(badges)) or "sale",
        "price": price,
        "sqm": sqm,
        "bedrooms": None,
        "city": city,
        "area": area,
        "location": ", ".join(p for p in (area, city) if p),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": "",
        "_sold": any(s in " ".join(badges).lower() for s in SOLD),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/properties", params={"status": 1, "page_size": PAGE_SIZE, "page": page})
        soup = BeautifulSoup(html, "html.parser")
        new_on_page = 0
        for a in soup.select('a[href*="/property/"]'):
            if not a.select_one(".card"):
                continue
            try:
                item = parse_card(a, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] in listings:
                continue
            listings[item["source_id"]] = item
            new_on_page += 1
        if new_on_page == 0:
            break
    for sub_id, name in SUBCATEGORIES.items():
        html = fetch(f"{base_url}/properties",
                     params={"status": 1, "page_size": 100, "subcategory_id[]": sub_id})
        for a in BeautifulSoup(html, "html.parser").select('a[href*="/property/"]'):
            m = re.search(r"/property/(\d+)", a.get("href", ""))
            if m and m.group(1) in listings:
                listings[m.group(1)]["type"] = name
    items = [i for i in listings.values() if not i.pop("_sold")]
    items.sort(key=lambda i: int(i["source_id"]), reverse=True)
    for rank, item in enumerate(items, 1):
        item["site_rank"] = rank
    return items, True
