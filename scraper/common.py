import re
import threading
import time
import unicodedata

import requests

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
REQUEST_DELAY = 1.0  # seconds between requests to the same site

_local = threading.local()  # sites are scraped in parallel threads, one session per thread


def _session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
        _local.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "el-GR,el;q=0.9"})
    return _local.session


def fetch(url, **kwargs):
    """GET a page politely (fixed delay, retry once on failure)."""
    for attempt in range(2):
        try:
            time.sleep(REQUEST_DELAY)
            r = _session().get(url, timeout=30, **kwargs)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt == 1:
                raise


def clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def parse_price(text):
    """'€ 150.000' -> 150000. Greek format uses '.' as thousands separator."""
    digits = re.sub(r"[^\d]", "", (text or "").split(",")[0])
    return int(digits) if digits else None


def parse_sqm(text):
    """'85.00 τ.μ.' -> 85.0, '1.200 τ.μ.' -> 1200.0, 'τ.μ.: 175' -> 175.0"""
    m = re.search(r"\d[\d.,]*", text or "")
    if not m:
        return None
    num = m.group(0).rstrip(".,")
    if re.fullmatch(r"\d+[.,]\d{1,2}", num):  # decimal part
        return float(num.replace(",", "."))
    return float(re.sub(r"[.,]", "", num))


def parse_int(text):
    m = re.search(r"\d+", text or "")
    return int(m.group(0)) if m else None


def normalize(text):
    """Lowercase and strip Greek accents so 'Ιωάννινα' matches 'ιωαννινα'."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def deal_from_text(text):
    """'Προς Πώληση' -> 'sale', 'Προς ενοικίαση' / 'Μίσθωση' -> 'rent'."""
    t = normalize(text)
    if "ενοικ" in t or "μισθ" in t or "rent" in t:
        return "rent"
    if "πωλ" in t or "sale" in t:
        return "sale"
    return None


# Every site names property types differently ("Οικόπεδα", "Plot of Land", "ΔΙΑΜΕΡΙΣΜΑ",
# "Διαμέρισμα δυάρι"); map them to one list so filters work across agencies. First match wins.
CANONICAL_TYPES = [
    ("Studio/Γκαρσονιέρα", ("γκαρσον", "studio", "στουντιο", "flatlet")),
    ("Μεζονέτα", ("μεζονετ", "duplex", "maisonette", "mezoneta")),
    ("Μονοκατοικία", ("μονοκατοικ", "βιλα", "βιλλα", "villa", "οικια", "κατοικι", "επαυλη", "αρχοντικ", "detached",
                      "house", "bungalow")),
    ("Διαμέρισμα", ("διαμερισμ", "διμερισμ", "οροφοδιαμ", "δυαρι", "τριαρι", "2αρι", "3αρι", "4αρι", "loft",
                    "πενθαουζ", "penthouse", "ρετιρε", "rooftop apartment", "apartment", "flat")),
    ("Αγροτεμάχιο", ("αγροτεμαχ", "αγροκτημα", "agricultural")),
    ("Οικόπεδο", ("οικοπεδ", "plot", "land", "parcel")),
    ("Κατάστημα", ("καταστημ", "shop", "store")),
    ("Κτίριο", ("κτιριο", "κτηριο", "πολυκατοικ", "συγκροτημα", "οικοδομη", "building", "residential complex")),
    ("Γραφείο", ("γραφει", "office")),
    ("Ξενοδοχείο", ("ξενοδοχ", "hotel", "τουριστικ", "καταλυμ")),
    ("Επιχείρηση", ("επιχειρη", "business")),
    ("Βιοτεχνικός χώρος", ("βιοτεχν", "light industrial")),
    ("Βιομηχανικός χώρος", ("βιομηχαν", "industrial", "εργοστασ", "factory")),
    ("Επαγγελματικός χώρος", ("επαγγελματικ", "αποθηκ", "warehouse", "εστιατορ", "αιθουσα", "commercial")),
    ("Parking", ("parking", "σταθμευσ", "παρκινγκ", "παρκιν", "γκαραζ")),
]
# keys match at the start of a word: "house" isn't "warehouse", "land" isn't "island"
_TYPE_PATTERNS = [(name, re.compile(r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keys) + ")"))
                  for name, keys in CANONICAL_TYPES]
# the only types kept (others are dropped by the runner): flats, offices, whole buildings, workshops
KEEP_TYPES = {"Studio/Γκαρσονιέρα", "Διαμέρισμα", "Κτίριο", "Βιοτεχνικός χώρος", "Βιομηχανικός χώρος", "Γραφείο"}


# broad categories some sites use as the "type"; the title is more specific, so check it first
BROAD_CATEGORIES = {"κατοικιες": "Μονοκατοικία", "γη": "Οικόπεδο", "επαγγελματικα ακινητα": "Επαγγελματικός χώρος"}


def canonical_type(*texts):
    """First text that names a known type wins: canonical_type(card_type, title, description)."""
    broad = [t for t in texts if normalize(clean(t)) in BROAD_CATEGORIES]
    generic = None
    for text in [t for t in texts if t not in broad] + broad:
        t = normalize(text)
        for name, pattern in _TYPE_PATTERNS:
            if pattern.search(t):
                if name != "Επαγγελματικός χώρος":
                    return name
                generic = generic or name  # "Επαγγελματικός χώρος" + title "Βιοτεχνικός χώρος …": the title wins
    if generic:
        return generic
    if broad:
        return BROAD_CATEGORIES[normalize(clean(broad[0]))]
    # nothing recognisable: keep a short type name, but not a whole sentence pulled from a title
    first = next((clean(t) for t in texts if clean(t)), None)
    return first if first and len(first.split()) <= 3 else "Άλλο"


def has_accents(text):
    return any(unicodedata.category(c) == "Mn" for c in unicodedata.normalize("NFD", text or ""))


def strip_admin(text):
    """'Δήμος Ιωαννίνων' / 'Ν. Ιωαννίνων' -> 'Ιωάννινα', 'Δήμος Θεσσαλονίκης' -> 'Θεσσαλονίκη'."""
    t = re.sub(r"^(Δήμος|Δ\.|Νομός|Ν\.|Περιφερειακή Ενότητα|Π\.Ε\.)\s*", "", clean(text), flags=re.I)
    n = normalize(t)
    if n in ("ιωαννινων", "ιωαννινα", "γιαννενα"):
        return "Ιωάννινα"
    if n in ("θεσσαλονικης", "θεσσαλονικη", "κεντρο θεσσαλονικης") or n.startswith("θεσσαλονικη υπολ"):
        return "Θεσσαλονίκη"
    return t


def split_place(text, sep=","):
    """'Σεισμόπληκτα, Ιωάννινα' -> ('Ιωάννινα', 'Σεισμόπληκτα'): last part is the city."""
    parts = [clean(p) for p in (text or "").split(sep) if clean(p)]
    if not parts:
        return "", ""
    return parts[-1], ", ".join(parts[:-1])
