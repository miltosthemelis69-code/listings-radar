"""Adapter for agency sites on the estateplus.gr platform (domus-estate.gr, foititikaspitia.eu).

Sales are listed at /listings?listingType=for+sale&sort=id&order=DESC&page=N, 10
.kf_listing_outer_wrap cards per page; the page header states the total ("178 ακίνητα").
Size is only in the card title ("Διαμέρισμα 52 τ.μ.").
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, parse_int, parse_price, parse_sqm, split_place

MAX_PAGES = 200


def parse_card(card, base_url):
    link = card.select_one(".kf_property_caption h5 a")
    title = clean(link.get_text())
    caption = card.select_one(".kf_property_caption p")
    code = caption.select_one("strong") if caption else None
    # caption reads "Κωδικός 2566 Πρέβεζα" (domus) or just "Ιωάννινα" (foititikaspitia)
    place = clean(caption.get_text()) if caption else ""
    if code:
        place = clean(place.replace("Κωδικός", "").replace(code.get_text(), "", 1))
    city, area = split_place(place)
    beds = None
    for li in card.select(".kf_property_dolar li"):
        if li.select_one(".fa-bed"):
            beds = parse_int(li.get_text())
    style = (card.select_one(".img-box-medium") or {}).get("style", "")
    img = re.search(r"url\(([^)]+)\)", style)
    if not img and card.select_one(".kf_property_img img"):  # some sites use a plain <img>
        img = re.match(r"(.*)", card.select_one(".kf_property_img img").get("src", "")) if card.select_one(".kf_property_img img").get("src") else None
    price = card.select_one(".kf_property_place > h5")
    label = card.select_one(".kf_rent_label2")
    return {
        "source_id": link["href"],
        "code": clean(code.get_text()) if code else link["href"],
        "url": urljoin(base_url + "/", link["href"]),
        "title": title,
        "type": clean(re.split(r"\d", title, maxsplit=1)[0]) or None,
        "deal": deal_from_text(label.get_text() if label else ""),
        "price": parse_price(price.get_text()) if price else None,
        "sqm": parse_sqm(title) if re.search(r"\d", title) else None,
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": place,
        "available_from": None,
        "image": urljoin(base_url + "/", img.group(1).strip("'\"")) if img else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/listings",
                     params={"listingType": "for sale", "sort": "id", "order": "DESC", "page": page})
        cards = BeautifulSoup(html, "html.parser").select(".kf_listing_outer_wrap")
        new_on_page = 0
        for card in cards:
            try:
                item = parse_card(card, base_url)
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
