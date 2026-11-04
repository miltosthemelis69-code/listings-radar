"""Adapter for Joomla sites using the OS Property component (e.g. ioanninahome.gr).

Each entry in site["list_paths"] is a category page (rentals, sales, ...) with its deal
type. Cards labelled Rented/Sold are old deals still on show and are skipped. Pages are
followed through the site's own "selida-N" pagination links, since extra query
params make the component return nothing. Cards carry no per-listing location
(the detail page only shows the agency's address), so location is the site's city.
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, fetch, normalize, parse_int, parse_price, parse_sqm

MAX_PAGES = 100


UNAVAILABLE_LABELS = ("rented", "sold", "ενοικιαστηκε", "πουληθηκε", "πωληθηκε", "πουλημενο", "ενοικιασμενο")


def parse_card(li, base_url, city, section_deal):
    link = li.select_one("a.property_mark_a")
    href = link["href"]
    img = li.select_one("img.ospitem-imgborder")
    img_src = img and (img.get("data-original") or img.get("src"))
    # the image folder holds the property's database id; listings without photos fall back to
    # the URL slug (not its trailing number: house4you slugs end in "-2" for duplicates' titles)
    m = re.search(r"/properties/(\d+)/", img_src or "")
    source_id = m.group(1) if m else href.rstrip("/").rsplit("/", 1)[-1]

    deal_el = li.select_one("figure h4")
    deal_text = normalize(deal_el.get_text()) if deal_el else ""
    deal = section_deal or ("rent" if ("ενοικ" in deal_text or "μισθ" in deal_text) else "sale" if "πωλ" in deal_text else None)

    prop_type = clean(li.select_one(".pcategory").get_text()) if li.select_one(".pcategory") else None
    name_el = li.select_one(".property-desc h4")
    name = clean(name_el.get_text()) if name_el else ""
    desc = li.select_one(".property-desc p")
    sqm = li.select_one(".property-icon-square span")
    beds = li.select_one(".property-icon-bed span")
    price = li.select_one(".price")
    code = re.match(r"/?[^/]*/([a-z]+-\d+)", href)

    return {
        "source_id": source_id,
        "code": code.group(1).upper() if code else source_id,
        "url": urljoin(base_url + "/", href),
        "title": " · ".join(x for x in [prop_type, name] if x),
        "type": prop_type,
        "deal": deal,
        "price": parse_price(price.get_text()) if price else None,
        "sqm": parse_sqm(sqm.get_text()) if sqm else None,
        "bedrooms": parse_int(beds.get_text()) if beds else None,
        "city": city,
        "area": "",
        "location": city,
        "available_from": None,
        "image": urljoin(base_url + "/", img_src) if img_src and "loader.gif" not in img_src else None,
        "description": clean(desc.get_text()) if desc else "",
        "_available": deal_text not in UNAVAILABLE_LABELS,
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    city = site.get("city", "")
    listings = {}
    for section in site["list_paths"]:  # {"path": "/akinita-new/rentals-ioannina", "deal": "rent"}
        url = urljoin(base_url + "/", section["path"].lstrip("/"))
        for page in range(1, MAX_PAGES + 1):
            soup = BeautifulSoup(fetch(url), "html.parser")
            for li in (fig.find_parent("li") for fig in soup.select(".property-mask .pimage")):
                try:
                    item = parse_card(li, base_url, city, section.get("deal"))
                except Exception as e:
                    print(f"  [{site['id']}] skipped card on {url}: {e}")
                    continue
                if item.pop("_available") and item["source_id"] not in listings:
                    item["site_rank"] = len(listings) + 1
                    listings[item["source_id"]] = item
            nxt = soup.select_one(f'a.page-link[href*="selida-{page + 1}/"]')
            if not nxt:
                break
            url = urljoin(base_url + "/", nxt["href"])
    return list(listings.values()), True
