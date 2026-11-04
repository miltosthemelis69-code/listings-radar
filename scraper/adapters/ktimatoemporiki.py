"""Adapter for ktimatoemporiki.gr (Astro site, Greece-wide agency).

Region pages such as /thessaloniki-prefecture?page=N (24 cards per page, header
"341 properties") carry each listing as JSON in the card's data-prop attribute:
{id, title, location, type, priceRaw, beds, size, plotSize, image, href}.
The config's `region_path` picks the region (default the Thessaloniki prefecture, the
area served by the Thessaloniki office; ids there start "th4-"). The site's /api/ is
disallowed by robots.txt and is not used.
"""
import html as htmllib
import json
import re

from scraper.common import clean, deal_from_text, fetch, parse_sqm

MAX_PAGES = 60
PROP_RE = re.compile(r'data-prop="(\{[^"]+)"')

# English type names (this site and grekodom.com) -> the Greek names the runner standardises
EN_TYPES = [
    ("studio", "Γκαρσονιέρα"), ("studo", "Γκαρσονιέρα"), ("maisonette", "Μεζονέτα"), ("townhouse", "Μεζονέτα"),
    ("penthouse", "Διαμέρισμα"), ("apartment", "Διαμέρισμα"), ("flat", "Διαμέρισμα"),
    ("villa", "Βίλα"), ("detached", "Μονοκατοικία"), ("house", "Μονοκατοικία"), ("cottage", "Μονοκατοικία"),
    ("hotel", "Ξενοδοχείο"), ("complex", "Συγκρότημα"), ("building", "Κτίριο"),
    ("agricultural", "Αγροτεμάχιο"), ("plot", "Οικόπεδο"), ("land", "Οικόπεδο"),
    ("office", "Γραφείο"), ("shop", "Κατάστημα"), ("store", "Κατάστημα"), ("retail", "Κατάστημα"),
    ("warehouse", "Αποθήκη"), ("industrial", "Βιομηχανικός χώρος"), ("business", "Επιχείρηση"),
    ("commercial", "Επαγγελματικός χώρος"), ("parking", "Parking"), ("garage", "Parking"),
]


def greek_type(*texts):
    for text in texts:
        t = (text or "").lower()
        for key, name in EN_TYPES:
            if key in t:
                return name
    return clean(texts[0]) if texts and texts[0] else None


def parse_prop(p, base_url):
    title = clean(p.get("title"))  # "Maisonette for Sale in Evosmos, Thessaloniki"
    # location: "Evosmos Thessaloniki, Thessaloniki Western Suburbs"
    loc = [clean(x) for x in (p.get("location") or "").split(",") if clean(x)]
    area = loc[0] if loc else ""
    city = "Θεσσαλονίκη"  # all cards are in the Thessaloniki prefecture; area names stay in English
    if area.endswith(" Thessaloniki") and area != "Thessaloniki":
        area = area[: -len(" Thessaloniki")]
    elif area == "Thessaloniki":
        area = loc[1] if len(loc) > 1 else ""
    m = re.match(r"(.+?) for (Sale|Rent)\b", title)
    ptype = greek_type(m.group(1) if m else "", p.get("type"))
    code = re.search(r"-id-([a-z0-9]+-\d+)$", p.get("href") or "")
    size = p.get("size") or p.get("plotSize") or ""
    return {
        "source_id": str(p["id"]),
        "code": code.group(1).upper() if code else str(p["id"]),
        "url": base_url + p["href"],
        "title": title,
        "type": ptype or None,
        "deal": deal_from_text(title) or "sale",
        "price": int(p["priceRaw"]) if p.get("priceRaw") else None,
        "sqm": parse_sqm(size.replace(",", "")) if size else None,
        "bedrooms": p.get("beds") or None,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": p.get("image") or None,
        "description": "",
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    path = site.get("region_path", "/thessaloniki-prefecture")
    listings, complete = {}, True
    for page in range(1, MAX_PAGES + 1):
        html = fetch(base_url + path, params={"page": page} if page > 1 else None)
        new_on_page = 0
        for raw in PROP_RE.findall(html):
            try:
                item = parse_prop(json.loads(htmllib.unescape(raw)), base_url)
            except Exception as e:
                print(f"  [{site['id']}] skipped card on page {page}: {e}")
                continue
            if item["source_id"] not in listings:
                item["site_rank"] = len(listings) + 1
                listings[item["source_id"]] = item
                new_on_page += 1
        if new_on_page == 0:
            break
    else:
        complete = False
    return list(listings.values()), complete
