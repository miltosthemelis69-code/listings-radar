"""Shared helpers for the WordPress real estate adapters (realhomes, wpresidence, estatik,
findeo, wpcpt): taxonomy terms with their parents, picking a type and a place out of a
listing's terms, euro prices in either number format, and sold/rented labels.
"""
import html
import json
import re

from scraper.common import clean, fetch, normalize

# "Πουλήθηκε", "Πωλήθηκε", "Sold", "Ενοικιάστηκε", "Rented", "Μισθώθηκε"
SOLD_RE = re.compile(r"πουληθηκ|πωληθηκ|\bsold\b|ενοικιαστηκ|μισθωθηκ|\brented\b|\bleased\b")

# umbrella categories that sites tick alongside the real type ("Κατοικία" + "Διαμέρισμα")
BROAD_TYPES = {"κατοικια", "κατοικιες", "οικιστικα", "residential", "επαγγελματικα", "επαγγελματικο",
               "επαγγελματικος χωρος", "επαγγελματικη στεγη", "commercial", "γη", "land", "λοιπα", "other", "αλλο"}

# region-level terms above the city ("Περιφέρεια Κεντρικής Μακεδονίας", "Central Macedonia")
REGION_RE = re.compile(r"περιφερει|region|macedonia|μακεδονι|greece|ελλαδα|νομος")

# municipality names as sites write them ("Δήμος Θεσσαλονίκης") -> the place name
GENITIVE_PLACES = {
    "θεσσαλονικης": "Θεσσαλονίκη", "καλαμαριας": "Καλαμαριά", "πυλαιας-χορτιατη": "Πυλαία-Χορτιάτης",
    "πυλαιας - χορτιατη": "Πυλαία-Χορτιάτης", "ωραιοκαστρου": "Ωραιόκαστρο", "θερμης": "Θέρμη",
    "θερμαικου": "Θερμαϊκός", "νεαπολης-συκεων": "Νεάπολη-Συκιές", "νεαπολης - συκεων": "Νεάπολη-Συκιές",
    "κορδελιου-ευοσμου": "Κορδελιό-Εύοσμος", "κορδελιου - ευοσμου": "Κορδελιό-Εύοσμος",
    "παυλου μελα": "Παύλος Μελάς", "αμπελοκηπων-μενεμενης": "Αμπελόκηποι-Μενεμένη",
    "αμπελοκηπων - μενεμενης": "Αμπελόκηποι-Μενεμένη", "δελτα": "Δέλτα", "χαλκηδονος": "Χαλκηδόνα",
    "λαγκαδα": "Λαγκαδάς", "βολβης": "Βόλβη", "κασσανδρας": "Κασσάνδρα", "πολυγυρου": "Πολύγυρος",
    "νεας προποντιδας": "Νέα Προποντίδα", "σιθωνιας": "Σιθωνία", "αριστοτελη": "Αριστοτέλης",
    "κατερινης": "Κατερίνη", "σερρων": "Σέρρες", "χαλκιδικης": "Χαλκιδική",
}
# English names some sites use (the runner's type/place lists are Greek)
EN_TYPES = [
    ("detached", "Μονοκατοικία"), ("house", "Μονοκατοικία"), ("villa", "Βίλα"), ("maisonette", "Μεζονέτα"),
    ("duplex", "Μεζονέτα"), ("studio", "Γκαρσονιέρα"), ("apartment", "Διαμέρισμα"), ("flat", "Διαμέρισμα"),
    ("penthouse", "Διαμέρισμα"), ("plot", "Οικόπεδο"), ("land", "Οικόπεδο"), ("office", "Γραφείο"),
    ("shop", "Κατάστημα"), ("store", "Κατάστημα"), ("retail", "Κατάστημα"), ("hotel", "Ξενοδοχείο"),
    ("business", "Επιχείρηση"), ("building", "Κτίριο"), ("complex", "Κτίριο"), ("storage", "Αποθήκη"),
    ("warehouse", "Αποθήκη"), ("commercial", "Επαγγελματικός χώρος"), ("parking", "Parking"),
    ("garage", "Parking"), ("island", "Οικόπεδο"), ("other", "Άλλο"),
]
EN_PLACES = {
    "thessaloniki": "Θεσσαλονίκη", "halkidiki": "Χαλκιδική", "chalkidiki": "Χαλκιδική", "attica": "Αττική",
    "athens": "Αθήνα", "kalamaria": "Καλαμαριά", "pieria": "Πιερία", "kavala": "Καβάλα", "serres": "Σέρρες",
    "limnos": "Λήμνος", "corfu": "Κέρκυρα", "crete": "Κρήτη", "thermi": "Θέρμη", "pylaia": "Πυλαία",
    "panorama": "Πανόραμα", "oraiokastro": "Ωραιόκαστρο", "kassandra": "Κασσάνδρα", "sithonia": "Σιθωνία",
    "athos": "Άθως", "evosmos": "Εύοσμος", "thermaikos": "Θερμαϊκός", "neapoli": "Νεάπολη",
}


def greek_type(name):
    """'Detached house' -> 'Μονοκατοικία'; Greek names pass through."""
    n = normalize(name)
    if "στουντιο" in n:  # Greek spelling of "studio"
        return re.sub(r"(?i)στούντιο|στουντιο", "Γκαρσονιέρα", name)
    return next((gr for en, gr in EN_TYPES if en in n), name) if re.search(r"[a-z]", n) else name


ADMIN_PREFIX = re.compile(r"^(Δήμος|Δημος|ΔΗΜΟΣ|Δ\.|Νομός|Ν\.|Municipality of|Mun\. of)\s*", re.I)


def api_get(url, **params):
    return json.loads(fetch(url, params=params or None))


def load_terms(api, rest_base):
    """{id: {"name", "parent"}} for every term of a taxonomy."""
    terms, page = {}, 1
    while True:
        data = api_get(f"{api}/{rest_base}", per_page=100, page=page, _fields="id,name,parent")
        terms.update({t["id"]: {"name": clean(html.unescape(t["name"])), "parent": t.get("parent", 0)} for t in data})
        if len(data) < 100:
            return terms
        page += 1


def taxonomies_for(api, post_type):
    """{taxonomy slug: rest_base} for the taxonomies of a post type."""
    data = api_get(f"{api}/taxonomies", type=post_type)
    return {slug: t.get("rest_base") or slug for slug, t in data.items()}


def most_specific(ids, terms):
    """Names of the assigned terms, children over their parents and real types over umbrella ones."""
    ids = [i for i in ids if i in terms]
    parents = {terms[i]["parent"] for i in ids}
    leaves = [i for i in ids if i not in parents] or ids
    names = [terms[i]["name"] for i in leaves]
    specific = [n for n in names if normalize(n) not in BROAD_TYPES]
    return specific or names


def chain(term_id, terms):
    out, seen = [], set()
    while term_id in terms and term_id not in seen:
        seen.add(term_id)
        out.insert(0, terms[term_id]["name"])
        term_id = terms[term_id]["parent"]
    return out


def place_name(name):
    """'Δήμος Θεσσαλονίκης' -> 'Θεσσαλονίκη', 'Αγία Σοφία, Δ. Θεσσαλονίκης' -> 'Αγία Σοφία'."""
    name = re.split(r",\s*(?:Δ\.|Mun\.|Δήμος|Municipality)", clean(name))[0]
    bare = ADMIN_PREFIX.sub("", name).strip()
    bare = re.sub(r"\s+Municipality$", "", bare, flags=re.I)
    key = normalize(bare)
    return GENITIVE_PLACES.get(key) or EN_PLACES.get(key) or bare or name


def split_city(name):
    """'Θεσσαλονίκη - Κέντρο' -> ('Θεσσαλονίκη', 'Κέντρο'); 'Καλαμαριά (Θεσσαλονίκη - Περιφ/κοί δήμοι)' ->
    ('Καλαμαριά', ''); 'Θεσσαλονίκης - Υπόλοιπο Νομού' -> ('Θεσσαλονίκη', ''). 'Πυλαία-Χορτιάτης' stays whole."""
    name = clean(re.sub(r"\s*\([^)]*\)", "", name))
    parts = re.split(r"\s+-\s+|(?<=Θεσσαλονίκη)-|(?<=Θεσσαλονίκης)-", name, maxsplit=1)
    sub = clean(parts[1]) if len(parts) > 1 else ""
    if re.match(r"υπολοιπ|περιφ|δημο", normalize(sub)):
        sub = ""
    return place_name(parts[0]), sub


def place_from_terms(ids, terms):
    """(city, area) from hierarchical location terms: the top non-region level is the city,
    the deepest term the area. Sites that name areas "Kalamaria, Thessaloniki" keep the first part."""
    chains = [c for c in (chain(i, terms) for i in ids if i in terms) if c]
    if not chains:
        return "", ""
    best = max(chains, key=len)
    levels = [n for n in best if not REGION_RE.search(normalize(n))] or best
    city, sub = split_city(levels[0].split(",")[-1])  # "Politechniou 33, Thessaloniki" -> "Thessaloniki"
    area = place_name(levels[-1]) if len(levels) > 1 else sub
    if len(levels) > 1 and split_city(levels[-1])[0] == city:  # leaf "Θεσσαλονίκη-Κηφισιά"
        area = split_city(levels[-1])[1]
    if "," in area and not re.search(r",\s*(?:Δ\.|Mun\.)", levels[-1]):
        area = clean(area.split(",")[0])
    return city, ("" if normalize(area) == normalize(city) else area)


PRICE_RE = re.compile(r"(\d{1,3}(?:[.,\s]\d{3})+|\d+)(?:[.,]\d{1,2})?\s*(?:€|eur|ευρ)", re.I)
PRICE_BEFORE_RE = re.compile(r"(?:€|eur)\s*(\d{1,3}(?:[.,\s]\d{3})+|\d+)", re.I)


def euro(text):
    """'150,000EUR', '€ 280.000', '230.000 €', '1.200.000,00 €' -> int euros (None when no price)."""
    text = clean(text)
    m = PRICE_RE.search(text) or PRICE_BEFORE_RE.search(text)
    if not m:
        return None
    value = int(re.sub(r"\D", "", m.group(1)))
    return value or None


def is_sold(*texts):
    return bool(SOLD_RE.search(normalize(" ".join(t or "" for t in texts))))


def text_of(node):
    return clean(node.get_text(" ", strip=True)) if node else ""
