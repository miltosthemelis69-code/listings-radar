"""Adapter for one Engel & Völkers shop (engelvoelkers.com, Next.js), e.g. Thessaloniki.

/gr/el/propertysearch?masterDataShopIds[]=<shop>&propertyMarketingType[]=sale
&normalizedStatuses[]=ACTIVE&sortingOptions[]=PUBLISHED_AT_DESC&page=N is server-rendered;
its __NEXT_DATA__ holds a react-query dehydrated state whose "listings" query has
listingsTotal and 23 listings a page (pageSize can't be raised). Each listing has id (UUID,
detail page /gr/el/exposes/<id>), displayId ("W-04BZ3Q"), propertyType, profile.title,
price.salesPrice.min, area.livingSurface / totalSurface, bedrooms.min, addressComponents
(locality, neighborhood), neighborhoodOverwrite, uploadCareImageIds and shopName.
Site keys: "shop_id" (Thessaloniki: "ebf4a63f") and "shop_name" (listings from any other
shop are dropped, in case the site's small-shop fallback widens the search).
"""
import json
import re

from scraper.common import clean, fetch

MAX_PAGES = 80
TYPES = {"apartment": "Διαμέρισμα", "house": "Μονοκατοικία", "villa": "Βίλα", "plot": "Οικόπεδο",
         "land": "Οικόπεδο", "commercial": "Επαγγελματικός χώρος", "office": "Γραφείο",
         "retail": "Κατάστημα", "hospitality": "Ξενοδοχείο", "parking": "Parking"}


def _min(block, key):
    v = (block or {}).get(key) or {}
    return v.get("min") if isinstance(v, dict) else v


def parse_listing(listing, base_url):
    comps = {c.get("placeType"): clean(c.get("text")) for c in listing.get("addressComponents") or []}
    city = (comps.get("locality") or comps.get("administrative_area_level_5")
            or comps.get("administrative_area_level_4") or comps.get("administrative_area_level_3") or "")
    area = clean(listing.get("neighborhoodOverwrite") or comps.get("neighborhood") or comps.get("sublocality") or "")
    if area == city:
        area = ""
    ptype = listing.get("propertyType") or ""
    sqm = _min(listing.get("area"), "livingSurface") or _min(listing.get("area"), "totalSurface") \
        or _min(listing.get("area"), "plotSurface")
    price = None if listing.get("hasPriceOnRequest") else _min(listing.get("price"), "salesPrice")
    imgs = listing.get("uploadCareImageIds") or []
    return {
        "source_id": listing["id"],
        "code": listing.get("displayId") or listing["id"],
        "url": f"{base_url}/gr/el/exposes/{listing['id']}",
        "title": clean((listing.get("profile") or {}).get("title") or ""),
        "type": TYPES.get(ptype, ptype) or None,
        "deal": {"sale": "sale", "rent": "rent"}.get(listing.get("propertyMarketingType")),
        "price": int(price) if price else None,
        "sqm": float(sqm) if sqm else None,
        "bedrooms": int(_min(listing, "bedrooms")) if _min(listing, "bedrooms") else None,
        "city": city,
        "area": area,
        "location": ", ".join(p for p in (area, city) if p),
        "available_from": None,
        "image": f"https://uploadcare.engelvoelkers.com/{imgs[0]}/-/preview/768x512/" if imgs else None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    shop_name = site.get("shop_name", "")
    listings = {}
    total = None
    complete = False
    for page in range(1, MAX_PAGES + 1):
        html = fetch(f"{base_url}/gr/el/propertysearch", params={
            "currency": "EUR", "marketCountryCode": "gr", "masterDataShopIds[]": site["shop_id"],
            "measurementSystem": "metric", "normalizedStatuses[]": "ACTIVE",
            "propertyMarketingType[]": "sale", "sortingOptions[]": "PUBLISHED_AT_DESC", "page": page})
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            break
        queries = json.loads(m.group(1))["props"]["pageProps"]["dehydratedState"]["queries"]
        data = next((q["state"]["data"] for q in queries if q["queryKey"][0] == "listings"), None) or {}
        total = data.get("listingsTotal", total)
        new_on_page = 0
        for entry in data.get("listings") or []:
            listing = entry.get("listing") or {}
            if shop_name and shop_name not in (listing.get("shopName") or ""):
                continue
            try:
                item = parse_listing(listing, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped listing {listing.get('id')}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0 or (total is not None and len(listings) >= total):
            complete = True
            break
    return list(listings.values()), complete
