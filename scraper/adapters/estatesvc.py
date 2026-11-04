"""Adapter for agency sites on the AngularJS "EstateSvc" CRM template (melathron.estate).

The page calls a JSON backend: POST /api?_mthd=EstateSvc::SearchRequest&lang=el with
{"data": {"ListingTypeID": 1, "ItemCategoryID": N, "IncludeTags": true}}. ListingTypeID 1 is
sale; categories are 1 residential, 2 commercial, 3 land. Each call returns every listing of
that category at once (each row carries TotalCount). Detail pages live at
/property/<ListingUrl>/<ListingCode>, photos at /images/user/<ImagePath>.
"""

from scraper.common import clean, deal_from_text, fetch, parse_int

CATEGORIES = (1, 2, 3)


def _tag(row, name):
    for t in row.get("Tags") or []:
        if t.get("TagName") == name:
            return t.get("TagValue")
    return None


def _post(base_url, payload):
    # fetch() only does GET; requests' session is reused through fetch's helper module
    from scraper.common import REQUEST_DELAY, _session
    import time
    for attempt in range(2):
        try:
            time.sleep(REQUEST_DELAY)
            r = _session().post(f"{base_url}/api", params={"_mthd": "EstateSvc::SearchRequest", "lang": "el"},
                                json={"data": payload}, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception:
            if attempt == 1:
                raise


def parse_row(row, base_url):
    city = clean(row.get("ListingCity") or row.get("ListingCounty") or "")
    area = clean(row.get("ListingDistrict") or "")
    if area == city:
        area = ""
    code = clean(str(row.get("ListingCode") or row["ID"]))
    type_ = clean(row.get("ItemTypeDescription") or "")
    img = row.get("ImagePath")
    loc = clean(row.get("LocDescriptionShort") or ", ".join(p for p in (area, city) if p))
    return {
        "source_id": str(row["ID"]),
        "code": code,
        "url": f"{base_url}/property/{row.get('ListingUrl') or 'l'}/{code}",
        "title": clean(row.get("ListingType") or type_) + (f", {loc}" if loc else ""),
        "type": type_ or None,
        "deal": deal_from_text(row.get("ListingTypeDescription") or "") or "sale",
        "price": int(row["CurrentPrice"]) if row.get("CurrentPrice") and not row.get("HidePrice") else None,
        "sqm": float(row["Size"]) if row.get("Size") else None,
        "bedrooms": parse_int(str(_tag(row, "Bedrooms") or "")) if _tag(row, "Bedrooms") else None,
        "city": city,
        "area": area,
        "location": ", ".join(p for p in (area, city) if p),
        "available_from": None,
        "image": f"{base_url}/images/user/{img}" if img else None,
        "description": clean(row.get("Description") or row.get("PartAutoDescription") or "")[:300],
        "_created": row.get("CreateDate") or "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    listings = {}
    complete = True
    for cat in site.get("categories", CATEGORIES):
        data = _post(base_url, {"ListingTypeID": 1, "ItemCategoryID": cat, "IncludeTags": True})
        if not data or data.get("success") is False:
            complete = False
            continue
        rows = data.get("data") or []
        if rows and rows[0].get("TotalCount") and rows[0]["TotalCount"] > len(rows):
            complete = False
        for row in rows:
            if row.get("Statusid") not in (None, 1):  # anything but active (sold/withdrawn)
                continue
            try:
                item = parse_row(row, base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped listing {row.get('ID')}: {e}")
                continue
            listings.setdefault(item["source_id"], item)
    items = sorted(listings.values(), key=lambda i: i.pop("_created"), reverse=True)
    for rank, item in enumerate(items, 1):
        item["site_rank"] = rank
    return items, complete
