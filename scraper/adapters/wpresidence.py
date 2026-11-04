"""Adapter for WordPress sites using the WPResidence theme (mesit.gr, tzemis.gr).

Price, size, bedrooms, place and status are read from the cards on the "for sale"
action-category archive (`list_path`, e.g. "action/sales/" or
"property_action_category/sales/"), 6-12 cards per page with /page/N/ pagination.
The cards don't name the property type, so types come from the REST API
(/wp-json/wp/v2/estate_property, `property_category` terms) when the site allows it,
otherwise from the property-category archives listed in the site's wp-sitemap
(some sites block the REST API with a security plugin).
"""
import html
import re
from urllib.parse import unquote

from bs4 import BeautifulSoup

from scraper.adapters.wptools import BROAD_TYPES, api_get, euro, greek_type, is_sold, load_terms, most_specific, text_of
from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_sqm

MAX_PAGES = 200


def archive_cards(url):
    """Yield (page soup, cards) for every page of an archive until a page adds nothing new."""
    seen = set()
    for page in range(1, MAX_PAGES):
        try:
            soup = BeautifulSoup(fetch(url + (f"page/{page}/" if page > 1 else "")), "html.parser")
        except Exception:
            if page == 1:
                raise
            return  # past the last page WordPress answers 404
        cards = [c for c in soup.select(".listing_wrapper[data-listid]") if c["data-listid"] not in seen]
        if not cards:
            return
        seen.update(c["data-listid"] for c in cards)
        yield soup, cards
        if not soup.select_one(f'a[href*="/page/{page + 1}/"]'):
            return


def city_name(city):
    """'Θεσσαλονίκη - Περιφερειακοί Δήμοι' / 'Θεσσαλονίκη Δήμος' -> 'Θεσσαλονίκη'."""
    return re.split(r"\s+-\s+|\s+Δήμος$|\s+Υπόλοιπο", clean(city))[0]


def parse_card(card):
    pid = card["data-listid"]
    link = card.select_one("h4 a")
    url = card.get("data-modal-link") or (link["href"] if link else None)
    title = clean(card.get("data-modal-title") or text_of(link))
    status = text_of(card.select_one(".status-wrapper")) or text_of(card.select_one(".action_tag_wrapper"))
    if is_sold(status, title):
        return None
    places = [text_of(a) for a in card.select(".property_location_image a")]
    city_links = [text_of(a) for a in card.select('.property_location_image a[href*="/city/"], .property_location_image a[href*="property_city"]')]
    city = city_links[-1] if city_links else (places[-1] if places else "")
    area = ", ".join(p for p in places if p != city)
    city = city_name(city)
    beds = card.select_one(".infobedrooms") or card.select_one(".inforoom")
    size = card.select_one(".infosize")
    img = card.select_one(".carousel-item img, .item img, img")
    desc = card.select_one(".listing_details.the_grid_view") or card.select_one(".listing_details")
    code = re.search(r"\b[ΤT]\s?(\d{3,})\b", title)
    return {
        "source_id": pid,
        "code": code.group(0).replace(" ", "") if code else pid,
        "url": url,
        "title": title,
        "type": None,
        "deal": deal_from_text(status),
        "price": euro(text_of(card.select_one(".listing_unit_price_wrapper"))),
        "sqm": parse_sqm(text_of(size)) if size else None,
        "bedrooms": parse_int(text_of(beds)) if beds else None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": (img.get("src") or img.get("data-original")) if img else None,
        "description": text_of(desc).rstrip(" .")[:300],
    }


def rest_sales(api):
    """{id: post} for every listing in a "for sale" action category, with its type."""
    actions = load_terms(api, "property_action_category")
    sale_ids = [i for i, a in actions.items() if deal_from_text(a["name"]) == "sale"]
    cats = load_terms(api, "property_category")
    posts, page = {}, 1
    while True:
        data = api_get(f"{api}/estate_property", property_action_category=",".join(map(str, sale_ids)),
                       per_page=100, page=page, _fields="id,link,date,title,property_category")
        for p in data:
            p["type"] = ", ".join(greek_type(n) for n in most_specific(p.get("property_category", []), cats)) or None
            posts[str(p["id"])] = p
        if len(data) < 100:
            return posts
        page += 1


def parse_detail(post):
    """A listing the archive pages skipped (some sites' pagination ends early): read its own page."""
    soup = BeautifulSoup(fetch(post["link"]), "html.parser")
    rows = {}
    for row in soup.select(".listing_detail"):
        label, _, value = text_of(row).partition(":")
        rows[clean(label)] = clean(value)
    status = text_of(soup.select_one(".property_title_label"))
    if is_sold(status):
        return None
    image = soup.select_one('meta[property="og:image"]')
    city, area = city_name(rows.get("Πόλη", "")), rows.get("Περιοχή", "")
    return {
        "source_id": str(post["id"]),
        "code": rows.get("Custom ID") or str(post["id"]),
        "url": post["link"],
        "title": clean(html.unescape(post["title"]["rendered"])),
        "type": post.get("type"),
        "deal": deal_from_text(status) or "sale",
        "price": euro(rows.get("Τιμή", "") or text_of(soup.select_one(".price_area"))),
        "sqm": parse_sqm(rows.get("Μέγεθος ακινήτου", "")),
        "bedrooms": parse_int(rows.get("Υπνοδωμάτια", "")),
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": image.get("content") if image else None,
        "description": "",
    }


def types_from_sitemap(base):
    """{listing id: type} by walking each property-category archive."""
    xml = fetch(f"{base}/wp-sitemap-taxonomies-property_category-1.xml")
    found = {}
    for loc in re.findall(r"<loc>([^<]+)</loc>", xml):
        url = html.unescape(loc)
        name = None
        for soup, cards in archive_cards(url if url.endswith("/") else url + "/"):
            if name is None:  # "Διαμέρισμα – Tzemis" -> "Διαμέρισμα"
                heading = soup.title or soup.select_one("h1")
                name = clean(re.split(r"\s+[–|-]\s+", text_of(heading))[0]) or \
                    unquote(url.rstrip("/").rsplit("/", 1)[-1]).replace("-", " ")
            for c in cards:
                found.setdefault(c["data-listid"], []).append(name)
    # several categories per listing ("Κατοικία" + "Διαμέρισμα"): keep the specific one
    return {k: ", ".join(greek_type(n) for n in specific_names(v)) for k, v in found.items()}


def specific_names(names):
    names = list(dict.fromkeys(names))
    return [n for n in names if normalize(n) not in BROAD_TYPES] or names


def scrape(site, known_ids=None):
    base = site["base_url"].rstrip("/")
    listings = []
    for _, cards in archive_cards(f"{base}/{site['list_path'].strip('/')}/"):
        for card in cards:
            item = parse_card(card)
            if item:
                item["site_rank"] = len(listings) + 1
                listings.append(item)
    try:
        posts = rest_sales(f"{base}/wp-json/wp/v2")
    except Exception:  # REST API blocked: types from the category archives, no detail fallback
        types = types_from_sitemap(base)
        for item in listings:
            item["type"] = types.get(item["source_id"]) or None
        return listings, True
    for item in listings:
        item["type"] = (posts.get(item["source_id"]) or {}).get("type")
    seen = {i["source_id"] for i in listings}
    for pid, post in posts.items():
        if pid not in seen:
            item = parse_detail(post)
            if item:
                item["site_rank"] = len(listings) + 1
                listings.append(item)
    return listings, True
