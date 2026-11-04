"""Adapter for agency websites hosted by spitogatos.gr ("Powered by spitogatos.gr").

These sites (liaggas-realestate.gr, viestate.gr, poliestate.gr, newhomesrealestate.gr,
natiordanou.gr, ...) share one backend; search pages are
/el/akinita/anazitisi?listingType=sale&category=<cat>&sortBy=dateuploaded|desc&page=N,
listing pages /el/akinito/<id>. The id is the spitogatos listing id (template1 shows it as
"Κωδ."). Two front-end templates are handled:
  - template7 (liaggas, viestate): <a class="ts-card"> cards, location in <aside>,
    "Εμβαδόν"/"Δωμάτια" in <dl>, total in "αγγελίες: N"
  - template1 (poliestate, newhomes, natiordanou): .listing-item cards, title
    "<type> προς πώληση <area> (<parent>)", total in #numResultsTop
Many sites on this platform sit behind Imperva; if a page is the "Pardon Our Interruption"
challenge or a 403/429, the scan stops for that site (never retried or worked around).
"""
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm

CATEGORIES = ["residential", "commercial", "land", "other"]
MAX_PAGES = 100
ID_RE = re.compile(r"/akinito/(\d+)")


class Blocked(Exception):
    pass


def _get(url, params):
    try:
        html = fetch(url, params=params)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (403, 429):
            raise Blocked(f"HTTP {e.response.status_code}")
        raise
    if "Pardon Our Interruption" in html:
        raise Blocked("Imperva challenge page")
    return html


def _split_title(title):
    """'Μεζονέτα προς πώληση Μαλακοπή (Τούμπα)' -> ('Μεζονέτα', 'προς πώληση', 'Μαλακοπή (Τούμπα)')"""
    m = re.match(r"(.*?)\s+(προς\s+(?:πώληση|ενοικίαση))\s*(.*)$", title, flags=re.I)
    if not m:
        return title, "", ""
    return clean(m.group(1)), m.group(2), clean(m.group(3))


def _place(area, city):
    area, city = clean(area), clean(city)
    return city, area, ", ".join(p for p in (area, city) if p)


def _is_closed(text):
    t = text.lower()
    return any(w in t for w in ("πουλήθηκε", "πωλήθηκε", "ενοικιάστηκε", "sold", "rented"))


def parse_template7(card, base_url):
    href = card["href"]
    title = clean(card.select_one("h4").get_text()) if card.select_one("h4") else ""
    ptype, deal_text, _ = _split_title(title)
    aside = card.select_one("aside")
    # aside reads "Κέντρο Θεσσαλονίκης, Λευκός Πύργος": broader area first, then neighbourhood
    parts = [clean(p) for p in clean(aside.get_text()).split(",")] if aside else []
    city, area, location = _place(", ".join(parts[1:]), parts[0] if parts else "")
    fields = {clean(dl.select_one("dt").get_text()): clean(dl.select_one("dd").get_text())
              for dl in card.select("dl") if dl.select_one("dt") and dl.select_one("dd")}
    img = card.select_one(".card-img")
    m = re.search(r"url\(([^)]+)\)", img.get("style", "") if img else "")
    badge = card.select_one(".ts-item__info-badge")
    return {
        "id": ID_RE.search(href).group(1), "url": urljoin(base_url + "/", href),
        "title": title, "type": ptype or None, "deal": deal_from_text(deal_text) or "sale", "std_title": bool(deal_text),
        "price": parse_price(badge.get_text()) if badge else None,
        "sqm": parse_sqm(fields.get("Εμβαδόν")) if fields.get("Εμβαδόν") else None,
        "bedrooms": parse_int(fields.get("Υπνοδωμάτια") or fields.get("Δωμάτια") or ""),
        "city": city, "area": area, "location": location,
        "image": m.group(1).strip("'\"") if m else None, "description": "",
        "closed": _is_closed(card.get_text()),
    }


def parse_template1(card, base_url):
    link = card.select_one(".listing-item-details a[href*='/akinito/']") or card.select_one("a[href*='/akinito/']")
    href = link["href"]
    h4 = card.select_one("h4")
    title = clean(h4.get_text()) if h4 else ""
    ptype, deal_text, place = _split_title(title)
    m = re.match(r"(.*?)\s*\(([^)]*)\)\s*$", place)
    city, area, location = _place(m.group(1), m.group(2)) if m else _place("", place)
    b = card.select_one(".listing-item-details b")
    sqm_el = b.select_one(".pull-right") if b else None
    price_text = clean(b.get_text()).replace(clean(sqm_el.get_text()), "") if b and sqm_el else (b.get_text() if b else "")
    beds = None
    for li in card.select(".listing-item-details li"):
        t = clean(li.get_text())
        if "υπνοδωμάτ" in t.lower():
            beds = parse_int(t)
    desc = ""
    for p in card.select(".listing-item-details p"):
        t = clean(p.get_text())
        if len(t) > 40 and not p.select_one("b") and "Κωδ" not in t:
            desc = t[:300]
            break
    code = card.select_one(".listing-item-code")
    img = card.select_one("img")
    return {
        "code": clean(code.get_text()).replace("Κωδ.", "").strip() if code else None,
        "id": ID_RE.search(href).group(1), "url": urljoin(base_url + "/", href),
        "title": title, "type": ptype or None, "deal": deal_from_text(deal_text) or "sale", "std_title": bool(deal_text),
        "price": parse_price(price_text) if "€" in price_text else None,
        "sqm": parse_sqm(sqm_el.get_text()) if sqm_el else None,
        "bedrooms": beds, "city": city, "area": area, "location": location,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": desc, "closed": _is_closed(card.get_text()),
    }


META_RE = re.compile(r'<meta name="description" content="([^"]*?)\s+(προς\s+(?:πώληση|ενοικίαση))\s+στην περιοχή\s+([^"]*)')


def fill_from_detail(card):
    """Agent-written titles ('Apartment, 75m²', '4267') carry no type/place; the detail page's
    meta description always reads '<type> προς πώληση στην περιοχή <area>, <city>, <prefecture>.'"""
    m = META_RE.search(_get(card["url"], None))
    if not m:
        return
    parts = [clean(p) for p in m.group(3).split(",") if clean(p)]
    card["type"] = clean(m.group(1))
    card["deal"] = deal_from_text(m.group(2)) or card["deal"]
    if len(parts) >= 2:
        card["city"], card["area"], card["location"] = _place(parts[0], parts[1])


def parse_page(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("a.ts-card[href*='/akinito/']")
    if cards:
        return [parse_template7(c, base_url) for c in cards]
    return [parse_template1(c, base_url) for c in soup.select(".listing-item")
            if c.select_one("a[href*='/akinito/']")]


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    search_url = f"{base_url}{site.get('list_path', '/el/akinita/anazitisi')}"
    listings, seen = {}, set()
    complete = True
    try:
        for cat in site.get("categories", CATEGORIES):
            for page in range(1, MAX_PAGES + 1):
                html = _get(search_url, {"listingType": "sale", "category": cat,
                                         "sortBy": "dateuploaded|desc", "page": page})
                new_on_page = 0
                for card in parse_page(html, base_url):
                    sid = card.pop("id")
                    if sid in seen:
                        continue
                    seen.add(sid)
                    new_on_page += 1
                    if card.pop("closed"):
                        continue
                    if not card.pop("std_title"):
                        fill_from_detail(card)
                    card.update(source_id=sid, code=card.get("code") or sid, available_from=None, site_rank=len(listings) + 1)
                    listings[sid] = card
                if new_on_page == 0:
                    break
            else:
                complete = False
    except Blocked as e:
        print(f"  [{site['id']}] blocked ({e}); stopped")
        complete = False
    return list(listings.values()), complete
