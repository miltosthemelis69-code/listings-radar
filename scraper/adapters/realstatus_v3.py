"""Adapter for older realstatus.gr themes that list on results.php but not as the
.property-list__item cards `realstatus.py` reads.

All of them take the same query: results.php?filter_int_to=1 (sales only) &orderby=1
(newest first) &page=N &locale=el_GR, and say "Βρέθηκαν N ακίνητα". Three card layouts:

- "propertyitem"  .propertyItem cards, 10 per page (estatecenter.gr, pisti-realestate.gr,
                  hellenic-home.gr, houseforyou.com.gr, fithome.gr, luxuryrealestate.gr)
- "casaroyal"     .property-list-item cards, 9 per page (olympusrealestate.gr)
- "listing"       .listings-container .listing-item cards (thesmosmesitiko.gr). The card has
                  no property type, so it is read from each listing's page (og:title
                  "Διαμέρισμα 90.00 τ.μ.") — one extra request per listing.

The layout is detected per page. Location is written "Area (Municipality)" (or
"(Municipality) Area" on casaroyal); the municipality becomes the city, falling back to
the optional `city` in the site config.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

MAX_PAGES = 200
SOLD = ("πουληθηκε", "πωληθηκε", "ενοικιαστηκε", "sold", "rented")


def price_of(text):
    """'€ 250.000' -> 250000; 'Απο € 188.000 τώρα € 175.000' -> 175000 (current price)."""
    text = clean(text)
    text = re.split(r"τώρα|τωρα|now", text, flags=re.I)[-1]
    return parse_price(text) if re.search(r"\d", text) else None


def place_of(text, default_city):
    """'Αγία Σοφία (Θεσσαλονίκη κέντρο)' -> ('Θεσσαλονίκη κέντρο', 'Αγία Σοφία');
    '(Καλαμαριά) Κέντρο' -> ('Καλαμαριά', 'Κέντρο'); 'Ροτόντα' -> (default, 'Ροτόντα')."""
    text = clean(text)
    m = re.search(r"\(([^)]*)\)", text)
    inner = clean(m.group(1)) if m else ""
    area = clean(re.sub(r"\([^)]*\)", "", text))
    if not inner or inner == area:
        return default_city, area
    return inner, area


def type_of(title):
    """'Διαμέρισμα 80.00 τ.μ.' / 'Γκαρσονιέρα προς πώληση' -> 'Διαμέρισμα' / 'Γκαρσονιέρα'."""
    t = clean(re.split(r"\d", title, maxsplit=1)[0])
    t = re.sub(r"\s*(προς|for)\s+(πώληση|πωληση|ενοικίαση|ενοικιαση|sale|rent)\s*$", "", t, flags=re.I)
    return clean(t) or None


def _id(href):
    m = re.search(r"id=(\d+)", href or "") or re.search(r"property/(\d+)", href or "")
    return m.group(1) if m else None


def parse_propertyitem(card, base_url, default_city):
    title_link = card.select_one(".rowText h4 a")
    img_link = card.select_one("a.propertyImgLink")
    source_id = _id(title_link["href"]) or _id(img_link["href"] if img_link else "")
    title = clean(title_link.get_text())
    paras = [p for p in card.select(".rowText > p") if "price" not in (p.get("class") or [])]
    texts = [clean(p.get_text()) for p in paras]
    code_i = next((i for i, t in enumerate(texts) if re.match(r"^(Κωδ|ID|Code)", t)), None)
    code = re.sub(r"^(Κωδ\.?|ID|Code)\s*:?\s*", "", texts[code_i]) if code_i is not None else source_id
    place = texts[code_i + 1] if code_i is not None and code_i + 1 < len(texts) else ""
    desc = texts[code_i + 2] if code_i is not None and code_i + 2 < len(texts) else ""
    city, area = place_of(place, default_city)

    sqm = beds = None
    for td in card.select(".propertyDetails td"):
        icon = (td.select_one("img") or {}).get("src", "") if td.select_one("img") else ""
        if "area" in icon and sqm is None and "€" not in td.get_text():  # 2nd "area" cell is €/τ.μ.
            sqm = parse_sqm(td.get_text())
        elif "bed" in icon:
            beds = parse_int(td.get_text())
    label = card.select_one(".propertyType")
    href = img_link["href"] if img_link else title_link["href"]
    img = card.select_one("img.propertyImg")
    price = card.select_one(".price")
    return {
        "source_id": source_id,
        "code": code,
        "url": urljoin(base_url + "/", href),
        "title": title,
        "type": type_of(title),
        "deal": deal_from_text(f"{href} {label.get_text() if label else ''}"),
        "price": price_of(price.get_text()) if price else None,
        "sqm": sqm if sqm else (parse_sqm(title) if re.search(r"\d", title) else None),
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": desc[:300],
        "_sold": any(s in normalize(card.get_text()) for s in SOLD),
    }


def parse_casaroyal(card, base_url, default_city):
    link = card.select_one('a[href*="property.php"]')
    source_id = _id(link["href"])
    title = clean(link.get_text())
    spans = [clean(s.get_text()) for s in card.select(".property-type")]
    code = next((re.sub(r"^Κωδ\.?\s*:?\s*", "", s) for s in spans if s.startswith("Κωδ")), source_id)
    place = next((s for s in spans if not s.startswith("Κωδ")), "")
    city, area = place_of(place, default_city)
    meta = [clean(x.get_text()) for x in card.select(".property-meta-item")]  # sqm, rooms, baths, floor
    img = card.select_one("img.myclass")
    friendly = re.search(r"location\.href\s*=\s*'([^']+)'", (img or {}).get("onclick", "") if img else "")
    price = card.select_one(".casaroyal-property-listing-time h4") or card.select_one("h4 b")
    return {
        "source_id": source_id,
        "code": code,
        "url": urljoin(base_url + "/", friendly.group(1) if friendly else link["href"]),
        "title": title,
        "type": type_of(title),
        "deal": deal_from_text(title),
        "price": price_of(price.get_text()) if price else None,
        "sqm": parse_sqm(meta[0]) if meta and "τ.μ" in meta[0] else None,
        "bedrooms": parse_int(meta[1]) if len(meta) > 1 else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": "",
        "_sold": any(s in normalize(card.get_text()) for s in SOLD),
    }


def parse_listing(card, base_url, default_city):
    link = card.select_one("a.listing-img-container") or card.select_one('a[href*="property"]')
    source_id = _id(link["href"])
    heading = card.select_one(".listing-title h4")
    title = clean(heading.get_text()) if heading else ""
    # location is the bare text after the map-marker icon: "Θεσσαλονίκη κέντρο Ιστορικό Κέντρο"
    place = ""
    marker = card.select_one(".listing-title .fa-map-marker")
    if marker and marker.next_sibling and isinstance(marker.next_sibling, str):
        place = clean(marker.next_sibling)
    sqm = beds = None
    for li in card.select(".listing-details li"):
        t = clean(li.get_text())
        if t.startswith("Εμβαδ"):
            sqm = parse_sqm(t)
        elif t.startswith("Δωμ") or t.startswith("Υπνοδ"):
            beds = parse_int(t)
    code = card.select_one(".listing-footer a")
    badges = " ".join(clean(s.get_text()) for s in card.select(".listing-badges span"))
    img = card.select_one(".listing-carousel img")
    price = card.select_one(".listing-price")
    return {
        "source_id": source_id,
        "code": re.sub(r"^Κωδικός\s*:?\s*", "", clean(code.get_text())) if code else source_id,
        "url": urljoin(base_url + "/", link["href"]),
        "title": title,
        "type": None,  # filled from the listing page
        "deal": deal_from_text(badges),
        "price": price_of(price.get_text()) if price else None,
        "sqm": sqm,
        "bedrooms": beds,
        "city": default_city,
        "area": place,
        "location": ", ".join(x for x in [place, default_city] if x),
        "available_from": None,
        "image": urljoin(base_url + "/", img["src"]) if img and img.get("src") else None,
        "description": "",
        "_sold": any(s in normalize(badges) for s in SOLD),
    }


def cards_of(soup):
    """-> (layout, cards)"""
    cards = soup.select(".propertyItem")
    if cards:
        return "propertyitem", cards
    cards = soup.select(".property-list-item.div-only-desktop") or soup.select(".property-list-item")
    if cards:
        return "casaroyal", cards
    cards = soup.select(".listings-container .listing-item")
    if cards:
        return "listing", cards
    return None, []


PARSERS = {"propertyitem": parse_propertyitem, "casaroyal": parse_casaroyal, "listing": parse_listing}


def fill_type_from_page(item):
    """og:title on the listing page: 'Διαμέρισμα 90.00 τ.μ.'"""
    try:
        soup = BeautifulSoup(fetch(item["url"]), "html.parser")
    except Exception as e:
        print(f"  could not read {item['url']}: {e}")
        return
    og = soup.select_one('meta[property="og:title"]')
    title = clean(og.get("content")) if og else ""
    # <title> is "Ιστορικό Κέντρο, Διαμέρισμα 90.00 τ.μ."; the card's place line is
    # "Θεσσαλονίκη κέντρο Ιστορικό Κέντρο" (municipality + area run together)
    page_title = clean(soup.title.get_text()) if soup.title else ""
    area = clean(page_title.split(",")[0]) if "," in page_title else ""
    if area:
        place = item["area"]
        municipality = clean(place[: -len(area)]) if place.endswith(area) else ""
        item["area"] = area
        if municipality and municipality != area:
            item["city"] = municipality
        item["location"] = ", ".join(x for x in [item["area"], item["city"]] if x)
    if title:
        item["type"] = type_of(title)
        if not item["sqm"]:
            item["sqm"] = parse_sqm(title) if re.search(r"\d", title) else None
        if title.lower() not in item["title"].lower():
            item["title"] = f"{title} – {item['title']}" if item["title"] else title


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    default_city = site.get("city", "")
    params = {"filter_int_to": 1, "orderby": 1, "locale": "el_GR", **site.get("params", {})}
    listings = {}
    layout = None
    for page in range(1, MAX_PAGES + 1):
        soup = BeautifulSoup(fetch(f"{base_url}/results.php", params={**params, "page": page}), "html.parser")
        page_layout, cards = cards_of(soup)
        layout = page_layout or layout
        new_on_page = 0
        for card in cards:
            try:
                item = PARSERS[page_layout](card, base_url, default_city)
            except Exception as e:  # one broken card shouldn't kill the run
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if not item["source_id"] or item.pop("_sold") or item["source_id"] in listings:
                continue
            item["site_rank"] = len(listings) + 1  # 1 = most recently published
            listings[item["source_id"]] = item
            new_on_page += 1
        if new_on_page == 0:  # past the last page (site repeats the last page or shows none)
            break
    if layout == "listing":
        for item in listings.values():
            fill_type_from_page(item)
    return list(listings.values()), True
