"""Adapter for karanikolas-estate.gr (Drupal 7 site, listings are nodes at /akinita/<nid>).

Sales are listed per type at /agora/<type>?field_locations_tid=All&page=N (0-based Drupal
pager, 4 teasers a page). Teasers only show a title, a price and a photo, so each listing's
own page is read for its facts: a <li><strong>Label:</strong>value</li> list with Εμβαδό,
Τιμή, Tύπος ακινήτου, Πρός (Αγορά / Ενοικίαση), Υπνοδωμάτια and an address block (street,
postal code, locality). The site has about 15 sales, so a full scan is ~35 requests.
There is no newest-first list; site_rank follows the node id, highest first.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

TYPES = ("diamerisma", "garsoniera", "studio", "mezoneta", "monokatoikia", "oikopedo", "epaggelmatikos-xoros")
MAX_PAGES = 30


def _list_ids(base_url, slug):
    """{nid: teaser image} for one /agora/<slug> listing."""
    found = {}
    for page in range(MAX_PAGES):
        html = fetch(f"{base_url}/agora/{slug}", params={"field_locations_tid": "All", "page": page})
        new = 0
        for a in BeautifulSoup(html, "html.parser").select('a[href^="/akinita/"]'):
            nid = re.search(r"/akinita/(\d+)", a["href"]).group(1)
            img = a.select_one("img")
            if nid not in found:
                found[nid] = None
                new += 1
            if img and img.get("src") and not found[nid]:
                found[nid] = urljoin(base_url + "/", img["src"])
        if new == 0:
            break
    return found


def parse_detail(html, nid, base_url, image):
    soup = BeautifulSoup(html, "html.parser")
    facts = {}
    for li in soup.select(".view-akinito-info li"):
        label = li.select_one("strong")
        if label:
            key = clean(label.get_text()).rstrip(":")
            label.extract()
            facts[key] = li
    text = {k: clean(v.get_text(" ")) for k, v in facts.items()}
    title_tag = soup.select_one("title")
    title = clean(title_tag.get_text().split("|")[0]) if title_tag else ""
    types = [clean(t) for t in text.get("Tύπος ακινήτου", text.get("Τύπος ακινήτου", "")).split(",") if clean(t)]
    addr = facts.get("Διεύθυνση")
    locality = clean(addr.select_one(".locality").get_text()) if addr and addr.select_one(".locality") else ""
    city = "Θεσσαλονίκη" if normalize(locality).startswith(("θεσ", "thess")) else locality.title()
    street = clean(addr.select_one(".thoroughfare").get_text()) if addr and addr.select_one(".thoroughfare") else ""
    price = parse_price(text.get("Τιμή", "").replace(" ", ""))
    body = soup.select_one(".field-name-body") or soup.select_one(".field-name-field-description")
    return {
        "source_id": nid,
        "code": nid,
        "url": f"{base_url}/akinita/{nid}",
        "title": title,
        "type": types[0] if types else None,
        "deal": deal_from_text("πώληση" if "αγορ" in normalize(text.get("Πρός", "")) else text.get("Πρός", "")),
        "price": price or None,
        "sqm": parse_sqm(text.get("Εμβαδό")) if text.get("Εμβαδό") else None,
        "bedrooms": parse_int(text.get("Υπνοδωμάτια")) if text.get("Υπνοδωμάτια") else None,
        "city": city,
        "area": "",
        "location": city,
        "available_from": None,
        "image": image,
        "description": (street + ". " if street else "") + (clean(body.get_text(" "))[:300] if body else ""),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    ids = {}
    for slug in TYPES:
        for nid, img in _list_ids(base_url, slug).items():
            ids.setdefault(nid, img)
    items = []
    for nid in sorted(ids, key=int, reverse=True):
        try:
            item = parse_detail(fetch(f"{base_url}/akinita/{nid}"), nid, base_url, ids[nid])
        except Exception as e:
            print(f"  [{site['id']}] skipped listing {nid}: {e}")
            continue
        if not item["price"] and not item["sqm"]:  # the agency's own "renovations" ad, not a property
            continue
        item["site_rank"] = len(items) + 1
        items.append(item)
    return items, True
