"""Floor, elevator and map point, read from each listing's own page.

List pages rarely show these, but almost every agency's detail page does, either in
a details table ("Όροφος: 2", "Ανελκυστήρας: Ναι", "2ος | Όροφος") or in the
description ("στον 3ο όροφο ... με ασανσέρ"). Each listing's page is fetched once and
the result kept (`details_checked`), so after the first backfill only new listings cost
a request. Whole buildings and workshops are skipped: floor/elevator don't apply.

Pages are cleaned before reading: hidden elements are dropped (several sites print
every possible feature and hide the ones that don't apply), as are search forms,
"similar properties" boxes and the agency's own address ("Ναπ. Ζέρβα 2, 2ος όροφος").
"""
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from bs4 import BeautifulSoup

from scraper.common import fetch, normalize

UNIT_TYPES = {"Διαμέρισμα", "Studio/Γκαρσονιέρα", "Γραφείο"}
MAX_PER_SITE = 400  # per run; a big backlog is spread over several runs

NOISE_TAGS = "script, style, nav, header, footer, form, select, option, input, label, button, iframe, noscript"
NOISE_CLASSES = re.compile(r"similar|related|nearby|recent|footer|cookie|search|navbar|breadcrumb|^hidden$|^d-none$|^sr-only$", re.I)
HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
# agency contact lines ("Ναπ. Ζέρβα 2, 2ος όροφος, γρ. 6", phone numbers, postcodes)
CONTACT_LINE = re.compile(r"\bγρ\.|τηλ|\b\d{5}\b|\b2\d{3}\s?\d{6}\b|\b69\d{8}\b|@|\[at\]|real estate,", re.I)

# accent-free, lowercase (text is normalize()d before matching)
ORDINALS = {"πρωτ": 1, "δευτερ": 2, "τριτ": 3, "τεταρτ": 4, "πεμπτ": 5, "εκτ": 6, "εβδομ": 7, "ογδο": 8}
LETTERS = {"α": 1, "β": 2, "γ": 3, "δ": 4, "ε": 5, "στ": 6, "ζ": 7, "η": 8}
ORDINAL_MARK = re.compile(r"\d\s*(ος|ο|ου|ον|η)\b|ισογει|ημι[οω]ροφ|υπογει|^(στ|[αβγδεζη])\s*['΄’`]|^(πρωτ|δευτερ|τριτ|τεταρτ|πεμπτ|εκτ)")
FLOOR_AFTER = re.compile(r"(?:^|\n)\s*(?:οροφος|floor)(?:\s*\([^)\n]*\))?\s*[:\-|]?\s*\n?\s*([^\n]{1,30})")
FLOOR_BEFORE = re.compile(r"(?:^|\n)\s*([^\n]{1,12})\n\s*(?:οροφος|floor)\s*(?:\n|$)")
FLOOR_PHRASE = re.compile(
    r"((?<![\d.,])\d{1,2}\s*(?:ος|ο|ου|ον)?|(?:πρωτ|δευτερ|τριτ|τεταρτ|πεμπτ|εκτ)\w*|(?:στ|[αβγδεζη])\s*['΄’`])\s+οροφ(?!οι|ων|ες)"
    r"|(υπερυψωμενο\s+ισογει\w*|ισογει\w*|ημιυπογει\w*|ημι[οω]ροφ\w*)")
ELEVATOR_LABEL = re.compile(r"(?:ανελκυστηρ\w*|ασανσερ|elevator|lift)\s*[:\-|]?\s*\n?\s*(ναι|οχι|yes|no)?\b")
NO_ELEVATOR = re.compile(r"(?:χωρις|δεν\s+(?:διαθετει|υπαρχει|εχει))\s+(?:\w+\s+){0,2}(?:ανελκυστ|ασανσ)")


def floor_value(text):
    """'2ος', '3 ο', 'Ισόγειο', 'Γ΄', 'τρίτου', 'Ημιώροφος', 'Υπόγειο' -> number (0 = ground)."""
    t = normalize(text).strip()
    if re.match(r"(υπερυψωμενο\s+)?ισογει", t):
        return 0
    if t.startswith(("ημιυπογει", "υπογει")):
        return -1
    if t.startswith(("ημιοροφ", "ημιωροφ", "μεσοροφ")):
        return 0.5
    m = re.match(r"(-?\d{1,2})(?!\d)", t)
    if m:
        return int(m.group(1))
    for word, n in ORDINALS.items():
        if t.startswith(word):
            return n
    m = re.match(r"(στ|[αβγδεζη])\s*['΄’`]", t)
    return LETTERS[m.group(1)] if m else None


def extract(text):
    """(floor, elevator) from page or description text; None where not stated."""
    t = normalize(text)
    floor = None
    # details table: prefer a value written as a floor ("2ος", "ισόγειο") over a bare number
    after = [m.group(1) for m in FLOOR_AFTER.finditer(t)]
    before = [m.group(1) for m in FLOOR_BEFORE.finditer(t)]
    candidates = [v for v in after + before if ORDINAL_MARK.search(v.strip())] + after
    for v in candidates:
        floor = floor_value(v)
        if floor is not None:
            break
    if floor is None:
        for m in FLOOR_PHRASE.finditer(t):
            floor = floor_value(m.group(1) or m.group(2))
            if floor is not None:
                break
    elevator = None
    if NO_ELEVATOR.search(t):
        elevator = False
    else:
        m = ELEVATOR_LABEL.search(t)
        if m:
            elevator = m.group(1) not in ("οχι", "no")
    return floor, elevator


def page_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.select(NOISE_TAGS):
        el.decompose()
    for el in soup.find_all(style=HIDDEN_STYLE) + soup.find_all(attrs={"class": NOISE_CLASSES}) \
            + soup.find_all(attrs={"id": NOISE_CLASSES}):
        # page wrappers carry classes like "cookies-not-set" or "search-enabled"; keep them
        if el.name in ("html", "body", "main", "article") or getattr(el, "decomposed", False):
            continue
        # a "noise" block that holds most of the page is a layout wrapper, not a sidebar
        if len(el.get_text()) > 0.5 * len(soup.get_text()):
            continue
        el.decompose()
    lines = soup.get_text("\n", strip=True).split("\n")
    return "\n".join(l for l in lines if not CONTACT_LINE.search(l))


# the property's own map point, as agency pages embed it for their map widget:
# LatLng(40.6, 22.9) · L.marker([40.6, 22.9]) · "lat": 40.6, "lng": 22.9 · data-lat="40.6" data-lng="22.9" · maps?q=40.6,22.9
_N = r"(-?\d{1,2}\.\d{3,})"
COORD_PATTERNS = [
    re.compile(r"LatLng\(\s*" + _N + r"\s*,\s*" + _N),
    re.compile(r"(?:marker|setView|center)\s*\(\s*\[\s*" + _N + r"\s*,\s*" + _N),
    re.compile(r"[\"']?(?:lat|latitude|property_lat|map_lat|geo_lat)[\"']?\s*[:=]\s*[\"']?" + _N + r"[\s\S]{0,120}?"
               r"[\"']?(?:lng|lon|long|longitude|property_lng|map_lng|geo_lng)[\"']?\s*[:=]\s*[\"']?" + _N, re.I),
    re.compile(r"data-(?:lat|latitude)=[\"']" + _N + r"[\"'][^>]{0,200}?data-(?:lng|lon|long|longitude)=[\"']" + _N, re.I),
    re.compile(r"(?:[?&](?:q|ll|center|daddr|query)=|@)" + _N + r"(?:,|%2C)\s*" + _N),
]


def coords(html):
    """[lat, lng] of the first map point in Greece on the page, or None."""
    for pattern in COORD_PATTERNS:
        for m in pattern.finditer(html):
            a, b = float(m.group(1)), float(m.group(2))
            if 34.5 < b < 42 and 19 < a < 30:  # some sites write lng, lat
                a, b = b, a
            if 34.5 < a < 42 and 19 < b < 30:
                return [round(a, 6), round(b, 6)]
    return None


def needs_floor(l):
    return l.get("type") in UNIT_TYPES and not l.get("details_checked")


def needs_page(l):
    return l.get("active") and l.get("url") and (needs_floor(l) or not l.get("coords_checked"))


def enrich(listings, now, log=print, max_per_site=MAX_PER_SITE):
    """Floor/elevator (flats, studios, offices) and the map point, from each listing's page, once."""
    todo = defaultdict(list)
    for l in listings:
        if needs_page(l):
            todo[l["site"]].append(l)

    def work(items):
        done = 0
        for l in items[:max_per_site]:
            try:
                html = fetch(l["url"])
            except Exception:
                continue  # try again next run
            if needs_floor(l):
                # the card's own text first: it can only be about this listing
                floor, elevator = extract(f"{l.get('title', '')}\n{l.get('description', '')}")
                if floor is None or elevator is None:
                    f2, e2 = extract(page_text(html))
                    floor = floor if floor is not None else f2
                    elevator = elevator if elevator is not None else e2
                l["floor"], l["elevator"], l["details_checked"] = floor, elevator, now
            l["coords"], l["coords_checked"] = coords(html), now
            done += 1
        return done

    if not todo:
        return 0
    with ThreadPoolExecutor(max_workers=24) as pool:
        counts = dict(zip(todo, pool.map(work, todo.values())))
    left = sum(len(v) for v in todo.values()) - sum(counts.values())
    log(f"details: {sum(counts.values())} listing pages read for floor/elevator/map point ({left} left)")
    return sum(counts.values())
