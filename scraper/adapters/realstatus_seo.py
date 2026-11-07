"""Adapter for realstatus.gr sites with SEO listing paths (skoreal.gr, domino-estate.gr).

Same card markup as `realstatus_v2` (.property-item cards with a.prop-link), but
/listings_async/page/N needs the browser's search state and answers 500 when called
directly. The server-rendered sale pages work: /<path>/page-N, 12 cards per page, e.g.
/poliseis-akiniton (domino, terrahomes: every sale) or /polisi-katoikies, /polisi-gi, …
(skoreal: one path per category). Set the sale paths in the site config as `list_paths`.
Sites on the /listings template (liberty.com.gr, elegancerealestate.gr) take
list_paths ["listings/for/1"] (sales only) with "page_format": "/page/{page}".

Skoreal's cards are a variant: free-text titles ("ΠΩΛΗΣΗ - ΚΑΤΟΙΚΙΑΣ - ΘΕΣΣΑΛΟΝΙΚΗ -
ΧΑΡΙΛΑΟΥ - ΔΙΑΜΕΡΙΣΜΑ"), place "Δήμος Θεσσαλονίκης , Χαριλάου", images as CSS
backgrounds, and the type only in the URL slug (/property/26535/Diamerisma-Charilaou).
"""
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scraper.adapters.realstatus_v2 import parse_card as parse_v2_card
from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

MAX_PAGES = 300
SOLD = ("πουληθηκε", "πωληθηκε", "ενοικιαστηκε", "sold", "rented")

# transliterated type at the start of skoreal's URL slugs
SLUG_TYPES = {
    "diamerisma": "Διαμέρισμα", "gkarsoniera": "Γκαρσονιέρα", "mezoneta": "Μεζονέτα",
    "monokatoikia": "Μονοκατοικία", "vila": "Βίλα", "loft": "Loft", "retire": "Διαμέρισμα",
    "rodaro": "Διαμέρισμα", "oikopedo": "Οικόπεδο", "agrotemachio": "Αγροτεμάχιο",
    "katastima": "Κατάστημα", "grafeio": "Γραφείο", "apothiki": "Αποθήκη",
    "biotechnikos": "Βιοτεχνικός χώρος", "ktirio": "Κτίριο", "parkingk": "Parking",
    "parking": "Parking", "xenodocheio": "Ξενοδοχείο", "epaggelmatikos": "Επαγγελματικός χώρος",
}


def parse_skoreal_card(card):
    link = card.select_one("a.prop-link")
    href = link["href"]
    source_id = re.search(r"/property/(\d+)", href).group(1)
    title = clean(card.select_one(".card-body h2").get_text()) if card.select_one(".card-body h2") else ""
    slug = href.rstrip("/").split("/")[-1] if not href.rstrip("/").endswith(source_id) else ""
    slug_type = SLUG_TYPES.get(normalize(slug.split("-")[0].split(" ")[0])) if slug else None
    place = card.select_one(".details-listing > span")
    # "Δήμος Θεσσαλονίκης , Χαριλάου" -> city, area
    parts = [clean(p) for p in (place.get_text() if place else "").split(",") if clean(p)]
    city = parts[0] if parts else ""
    area = ", ".join(parts[1:])
    sqm = beds = None
    for li in card.select(".listing-icons li"):
        icon = " ".join(li.select_one("i").get("class", [])) if li.select_one("i") else ""
        if "object-group" in icon or "ruler" in icon:
            sqm = parse_sqm(li.get_text())
        elif "bed" in icon:
            beds = parse_int(li.get_text())
    img = card.select_one(".img-item")
    img_url = re.search(r"url\(([^)]+)\)", img.get("style", "")) if img else None
    label = card.select_one(".labels .label")
    price = card.select_one(".price-p") or card.select_one(".listing-price")
    for old in price.select(".oldprice, del, s") if price else []:
        old.decompose()  # a reduced price shows the old one first: "175.000 € 170.000 €"
    code = card.select_one(".prop-id b") or card.select_one(".prop-id")
    return {
        "source_id": source_id,
        "code": clean(code.get_text()).replace("Κωδ.", "").strip() if code else source_id,
        "url": href,
        "title": title.capitalize(),
        "type": slug_type,  # None -> the runner reads the type from the title
        "deal": deal_from_text(f"{label.get_text() if label else ''} {title}"),
        "price": parse_price(price.get_text()) if price and re.search(r"\d", price.get_text()) else None,
        "sqm": sqm,
        "bedrooms": beds,
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "image": img_url.group(1).strip("'\"") if img_url else None,
        "description": "",
    }


def parse_card(card, base_url):
    item = parse_skoreal_card(card) if card.select_one(".details-listing") else parse_v2_card(card)
    item["url"] = urljoin(base_url + "/", item["url"])  # terrahomes links are relative
    # "Θεσσαλονίκη Περιφ/κοί δήμοι, Καλαμαριά, Βότση": the municipality is the city
    parts = [p for p in item["area"].split(", ") if p]
    if "Περιφ" in item["city"] and parts:
        item["city"], item["area"] = parts[0], ", ".join(parts[1:])
        item["location"] = ", ".join(x for x in [item["area"], item["city"]] if x)
    return item


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    page_fmt = site.get("page_format", "/page-{page}")  # liberty/elegance: "/page/{page}"
    listings = {}
    for path in site["list_paths"]:
        for page in range(1, MAX_PAGES + 1):
            url = f"{base_url}/{path.strip('/')}" + (page_fmt.format(page=page) if page > 1 else "")
            soup = BeautifulSoup(fetch(url), "html.parser")
            new_on_page = 0
            for card in soup.select(".property-item"):
                if not card.select_one("a.prop-link"):
                    continue
                if any(s in normalize(card.get_text()) for s in SOLD):
                    continue
                try:
                    item = parse_card(card, base_url)
                except Exception as e:
                    print(f"  [{site['id']}] skipped card on {path} page {page}: {e}")
                    continue
                if item["source_id"] not in listings:
                    item["site_rank"] = len(listings) + 1  # newest first within each path
                    listings[item["source_id"]] = item
                    new_on_page += 1
            if new_on_page == 0:
                break
    return list(listings.values()), True
