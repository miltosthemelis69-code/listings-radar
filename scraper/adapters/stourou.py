"""Adapter for stourou.gr (Olga Stourou, Hostinger Website Builder / Zyro site).

The site has no listing index or data API: each property is a hand-written page, and the
only list of them is /sitemap.xml. Every page in the sitemap (except the fixed info pages)
is read and kept when it looks like a property, i.e. its title or text gives a price.
Facts come from free text: the <title> ("Θεσσαλονίκη – Πέτρου Συνδίκα 80τ.μ. ... 145.000€")
and labelled lines in the body ("Τιμή: 145.000€", "Εμβαδόν: 80τ.μ.", "Υπνοδωμάτια: 2",
"Κωδικός Ακινήτου: ΟΣΤ84829"). The place is the title's first segment before "–" when it
is short. Expect some gaps; a page with no price is skipped. There is no order on the site,
so site_rank follows the sitemap.
"""
import re

from bs4 import BeautifulSoup

from scraper.common import clean, deal_from_text, fetch, normalize, parse_int, parse_price, parse_sqm

INFO_PAGES = {"", "biografiko", "epikoinwnia", "cookies", "oroi-xrhshs", "proswpika-dedomena",
              "mi-newsletter", "akinhta"}
SOLD = ("πωληθηκε", "πουληθηκε", "sold", "ενοικιαστηκε")
# places named in this agent's titles, checked in order when the title has no short place prefix
PLACES = [("θερμη", "Θέρμη"), ("περαια", "Περαία"), ("πυργαδικια", "Πυργαδίκια"), ("φλογητα", "Φλογητά"),
          ("καλοχωρι", "Καλοχώρι"), ("θεσσαλονικ", "Θεσσαλονίκη"), ("μοναστηριου", "Θεσσαλονίκη"),
          ("συνδικα", "Θεσσαλονίκη")]
PRICE_RE = r"(\d{1,3}(?:\.\d{3})+|\d{4,})\s*(?:€|ευρω|euro)"


def _utf8(text):
    """The server sends no charset, so requests decodes the UTF-8 pages as Latin-1."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def parse_page(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.select_one("title")
    title = clean(title_tag.get_text().split("| Olga Stourou")[0]) if title_tag else ""
    og = soup.find("meta", property="og:image")
    for tag in soup(["script", "style", "header", "footer", "nav"]):
        tag.decompose()
    text = clean(soup.get_text(" "))
    norm = normalize(title + " " + text[:400])
    if any(s in norm for s in SOLD):
        return None

    m = re.search(r"Τιμή\s*:\s*" + PRICE_RE, text, re.I) or re.search(PRICE_RE, title, re.I)
    price = parse_price(m.group(1)) if m else None
    if not price:
        return None
    m = re.search(r"Εμβαδ\w*\s*:\s*([\d.,]+)\s*τ\.?μ", text) or re.search(r"([\d.,]+)\s*τ\.?\s?μ", title)
    sqm = parse_sqm(m.group(1)) if m else None
    m = re.search(r"Υπνοδωμάτια\s*:\s*(\d+)", text)
    beds = parse_int(m.group(1)) if m else None
    m = re.search(r"Κωδικός Ακινήτου\s*:\s*([A-Za-zΑ-Ωα-ω]*\d+)", text)
    slug = url.rstrip("/").rsplit("/", 1)[-1]

    first = clean(re.split(r"\s[–|-]\s", title)[0])
    place = first if len(first.split()) <= 2 and not re.search(r"\d", first) else ""
    if not place:
        place = next((name for key, name in PLACES if key in normalize(title)), "")
    kind = "Διαμέρισμα" if "ρετιρε" in normalize(title) else None
    return {
        "source_id": slug,
        "code": m.group(1) if m else slug,
        "url": url,
        "title": title,
        "type": kind,  # None: the runner reads the type from the title
        "deal": deal_from_text(title) or "sale",
        "price": price,
        "sqm": sqm,
        "bedrooms": beds,
        "city": place,
        "area": "",
        "location": place,
        "available_from": None,
        "image": og.get("content") if og else None,
        "description": text[len(title):][:300].strip(),
    }


def scrape(site, known_ids=None):
    base_url = site["base_url"].rstrip("/")
    urls = re.findall(r"<loc>([^<]+)</loc>", fetch(f"{base_url}/sitemap.xml"))
    items = []
    for url in urls:
        slug = url.replace(base_url, "").strip("/")
        if slug in INFO_PAGES:
            continue
        try:
            item = parse_page(_utf8(fetch(url)), url)
        except Exception as e:
            print(f"  [{site['id']}] skipped {url}: {e}")
            continue
        if item:
            item["site_rank"] = len(items) + 1
            items.append(item)
    return items, True
