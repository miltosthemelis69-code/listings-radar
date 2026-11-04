"""Adapter for WordPress sites that keep listings in their own custom post type, built with
Elementor + ACF / JetEngine rather than a real estate theme (civilhome.gr, kosmopolishouse.gr,
g-mas.gr).

The post type and its taxonomies come from the WP REST API (/wp-json/wp/v2/<post_type>):
deal ("Πώληση" / "Αγορά"), type, place. Price and size are custom fields the API leaves
out, so they are read either
- from each listing's own page ("Τιμή : 115.000 €", "Εμβαδόν 72 τ.μ.") - fine for a few
  dozen listings - or
- from a JetEngine listing grid page that shows every listing with its price
  (`grid_path`, paginated /page/N/), matched by post id.

Site config:
  post_type        REST base of the listings ("akinito", "house", "property")
  deal_taxonomy    taxonomy holding sale / rent; its "sale" terms filter the query
  type_taxonomy    optional; otherwise the type is the title's first words
  place_taxonomy   optional hierarchical place terms (city > area)
  bedrooms_taxonomy optional (terms named "1", "2", ...)
  grid_path        optional JetEngine grid page with prices (else detail pages are read);
                   "{page}" in it is replaced by the page number, else /page/N/ is appended
  city             optional default city
"""
import html
import re

from bs4 import BeautifulSoup

from scraper.adapters.wptools import (
    api_get, euro, greek_type, is_sold, load_terms, most_specific, place_from_terms, taxonomies_for, text_of)
from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_sqm, split_place

PER_PAGE = 100
MAX_GRID_PAGES = 200
SQM_IN_TITLE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:τ\.?\s?μ|m²|τμ\b)", re.I)
BEDS_IN_TITLE = re.compile(r"\b(\d)\s*Δ(?=Σ|Κ)")  # "3ΔΣΚΜΠ" = 3 bedrooms, living room, kitchen, bath
RELATED = re.compile(r"\n(Δείτε Επίσης|Παρόμοια|Σχετικά ακίνητα|Similar|Related)", re.I)


def deal_of(name):
    n = normalize(name)
    if "αγορ" in n or "buy" in n:  # "Αγορά" = for sale (the buyer's view)
        return "sale"
    return deal_from_text(name)


def label_value(text, *labels):
    """'Τιμή :\\n115.000 €' -> '115.000 €' (value on the same line or the next one)."""
    for label in labels:
        m = re.search(rf"(?:^|\n)\s*{label}\s*:?\s*\n?\s*([^\n]+)", text, re.I)
        if m and clean(m.group(1)) not in (":", ""):
            return clean(m.group(1).lstrip(": "))
    return ""


def page_text(url):
    soup = BeautifulSoup(fetch(url), "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer", "nav", "form"]):
        tag.decompose()
    text = re.sub(r"\n\s*\n+", "\n", (soup.body or soup).get_text("\n", strip=True))
    return RELATED.split(text)[0]


def fill_from_detail(item):
    text = page_text(item["url"])
    item["price"] = euro(label_value(text, "Τιμή", "Price")) or euro(text)
    size = label_value(text, r"Εμβαδ[όοά]ν?", "Επιφάνεια", "Size")
    item["sqm"] = item["sqm"] or (parse_sqm(size) if size else None)
    item["bedrooms"] = item["bedrooms"] or parse_int(label_value(text, "Υπνοδωμάτια", "Bedrooms"))
    code = label_value(text, r"[KΚ]ωδικός\s+[Aα]κινήτου", "Κωδικός")
    if code:
        item["code"] = code
    address = label_value(text, "Διεύθυνση")
    if address and not item["city"]:
        item["city"], item["area"] = split_place(address.split("|")[-1])  # "Αποστόλου Παύλου | Άνω Πόλη, Θεσσαλονίκη"
        item["location"] = ", ".join(x for x in [item["area"], item["city"]] if x)
    status = label_value(text, "Κατάσταση", "Status")
    return not is_sold(status)


def fill_from_grid(base, grid_path, by_id):
    seen = set()
    for page in range(1, MAX_GRID_PAGES):
        if "{page}" in grid_path:  # JetSmartFilters URL paging: "el/akinita/?jsf=jet-engine:<query id>&pagenum={page}"
            url = f"{base}/{grid_path.lstrip('/').format(page=page)}"
        else:
            url = f"{base}/{grid_path.strip('/')}/" + (f"page/{page}/" if page > 1 else "")
        try:
            soup = BeautifulSoup(fetch(url), "html.parser")
        except Exception:
            if page == 1:
                raise
            break
        items = [x for x in soup.select(".jet-listing-grid__item[data-post-id]") if x["data-post-id"] not in seen]
        if not items:
            break
        for x in items:
            seen.add(x["data-post-id"])
            item = by_id.get(x["data-post-id"])
            if item:
                text = text_of(x)
                item["price"] = euro(text)
                item["_sold"] = is_sold(text)
    return seen


def scrape(site, known_ids=None):
    base = site["base_url"].rstrip("/")
    api = f"{base}/wp-json/wp/v2"
    post_type = site["post_type"]
    tax = taxonomies_for(api, post_type)
    keys = {k: site.get(k) for k in ("deal_taxonomy", "type_taxonomy", "place_taxonomy", "bedrooms_taxonomy")}
    terms = {k: load_terms(api, tax.get(slug, slug)) if slug else {} for k, slug in keys.items()}
    field = lambda k: tax.get(keys[k], keys[k])

    deal_terms = terms["deal_taxonomy"]
    sale_ids = site.get("sale_terms") or [i for i, t in deal_terms.items() if deal_of(t["name"]) == "sale"]
    params = {"per_page": PER_PAGE, "orderby": "date", "order": "desc", "_embed": "wp:featuredmedia"}
    if sale_ids:
        params[field("deal_taxonomy")] = ",".join(map(str, sale_ids))

    listings, page = [], 1
    while True:
        data = api_get(f"{api}/{post_type}", **params, page=page)
        for p in data:
            item = parse_post(p, site, terms, field)
            if item:
                listings.append(item)
        if len(data) < PER_PAGE:
            break
        page += 1

    if site.get("grid_path"):
        fill_from_grid(base, site["grid_path"], {i["source_id"]: i for i in listings})
        listings = [i for i in listings if not i.pop("_sold", False)]
    else:
        kept = []
        for item in listings:
            try:
                if fill_from_detail(item):
                    kept.append(item)
            except Exception as e:
                print(f"  [{site['id']}] could not read {item['url']}: {e}")
                kept.append(item)
        listings = kept
    for rank, item in enumerate(listings, 1):
        item["site_rank"] = rank
        if not item["city"] and site.get("city"):
            item["city"] = site["city"]
            item["location"] = ", ".join(x for x in [item["area"], item["city"]] if x)
    return listings, True


def parse_post(p, site, terms, field):
    ids = lambda k: p.get(field(k), []) if site.get(k) else []
    title = clean(html.unescape(p["title"]["rendered"]))
    deal_names = [terms["deal_taxonomy"][i]["name"] for i in ids("deal_taxonomy") if i in terms["deal_taxonomy"]]
    deals = {deal_of(n) for n in deal_names} - {None}
    types = [greek_type(n) for n in most_specific(ids("type_taxonomy"), terms["type_taxonomy"])]
    city, area = place_from_terms(ids("place_taxonomy"), terms["place_taxonomy"])
    beds = [terms["bedrooms_taxonomy"][i]["name"] for i in ids("bedrooms_taxonomy") if i in terms["bedrooms_taxonomy"]]
    sqm = SQM_IN_TITLE.search(title)
    bed_title = BEDS_IN_TITLE.search(title)
    media = (p.get("_embedded") or {}).get("wp:featuredmedia") or [{}]
    excerpt = re.sub(r"<[^>]+>", " ", html.unescape((p.get("excerpt") or {}).get("rendered", "")))
    return {
        "source_id": str(p["id"]),
        "code": str(p["id"]),
        "url": p["link"],
        "title": title,
        # no type taxonomy: "Ανακαινισμένη Γκαρσονιέρα – 194" -> "Ανακαινισμένη Γκαρσονιέρα"
        "type": ", ".join(types) or greek_type(clean(re.split(r"\s+[–-]\s+|,|\s\d", title)[0])) or None,
        "deal": "sale" if deals == {"sale"} else (deals.pop() if len(deals) == 1 else deal_from_text(title)),
        "price": None,
        "sqm": parse_sqm(sqm.group(1)) if sqm else None,
        "bedrooms": parse_int(beds[0]) if beds else (int(bed_title.group(1)) if bed_title else None),
        "city": city,
        "area": area,
        "location": ", ".join(x for x in [area, city] if x),
        "available_from": None,
        "listed_at": p.get("date"),
        "image": media[0].get("source_url"),
        "description": clean(excerpt)[:300],
    }
