"""Map positions for listings.

Most agency pages embed the property's own map point (read by details.py into `coords`).
It is used when it isn't the agency's office (a point many of its listings share) and lies
in Greece; a point outside the agency's prefecture moves the listing to "Άλλη περιοχή"
(an Ioannina agency selling in Preveza), unless the listing names the agency's own city,
then the point is wrong and dropped.

Otherwise the listing is placed at its area. Each place name ("Κάτω Τούμπα", "Βρυσούλα") is
looked up once on OpenStreetMap's free Nominatim service and its candidates are kept in the
data file's "geo" table, so a normal run only looks up names it hasn't seen (at most
MAX_LOOKUPS, 1 per second, as Nominatim asks). Only places count (suburbs, neighbourhoods,
villages, municipalities), never streets or shops: "Μπότσαρη" is a neighbourhood, not one of
the city's Μπότσαρη streets. Names are common ("Τούμπα" is also a village near Serres,
"Βρυσούλα" one in Zitsa), so of a name's candidates the one nearest the listing's broader
place wins ("Αμπελόκηποι, Δημαρχείου": the square in Αμπελόκηποι, not Kalamaria's), and
for a listing in the city, the one nearest the city centre. The most specific place found
gives the pin, which shows the neighbourhood, not the building (`exact` is not set).
"""
import math
import re
import time
from collections import Counter

import requests

from scraper.common import normalize

MAX_LOOKUPS = 150
URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "ListingsRadar/1.0 (personal real estate dashboard)"}
# lon_min, lat_min, lon_max, lat_max
BOXES = {
    "Θεσσαλονίκη κέντρο": (22.87, 40.56, 23.02, 40.68),  # the city itself: "Ανάληψη" is the city's, not Lagkadas'
    "Θεσσαλονίκη": (22.55, 40.35, 23.95, 41.0),
    "Χαλκιδική": (22.95, 39.9, 24.45, 40.65),
    "Ιωάννινα": (20.2, 39.35, 21.4, 40.35),  # the prefecture: not Preveza, Arta or Aetolia
    "Ελλάδα": (19.3, 34.7, 29.7, 41.8),
}
CENTRES = {"Θεσσαλονίκη": (40.6325, 22.945), "Ιωάννινα": (39.665, 20.853)}
CITY_KM = 8       # a Thessaloniki city listing's neighbourhood is this close to the centre
NEAR_KM = 6       # a specific name must be this close to the broader place it is in
CITY_STEMS = {"Θεσσαλονίκη": ("θεσσαλονικ", "thessalonik"), "Ιωάννινα": ("ιωαννιν", "ιωανιν", "ioannin")}
GENERIC = {"κεντρο", "center", "centre", "επεκταση", "γενικα", "περιφ", "κοι δημοι", "προαστια", "suburbs",
           "περιχωρα", "υπολοιπες περιοχες", "λοιπες χωρες", "βορεια ελλαδα", "κεντρικη ελλαδα", "μακεδονια",
           "θεσσαλονικη κεντρο", "ιστορικο κεντρο", "ανατολικη", "δυτικη", "πολη"}


def box_for(l):
    if l.get("zone") in ("Άλλη περιοχή", "Εξωτερικό"):
        return "Ελλάδα"
    if l.get("zone") == "Χαλκιδική":
        return "Χαλκιδική"
    if l.get("region") == "Θεσσαλονίκη" and not l.get("zone"):
        return "Θεσσαλονίκη κέντρο"
    return l.get("region") or "Ιωάννινα"


def names(l):
    """Place names of a listing, cleaned: 'Code Kassandra' -> 'Kassandra', ': Τούμπα' -> 'Τούμπα'."""
    out = []
    for p in re.split(r",| - |/| – ", f"{l.get('area') or ''},{l.get('city') or ''}"):
        p = re.sub(r"^(code|περιοχη)\s+", "", re.sub(r"\(.*?\)", "", p).strip(" :.-"), flags=re.I).strip()
        if p and normalize(p) not in GENERIC and not normalize(p).startswith("κοι δημ") and p not in out:
            out.append(p)
    return out


def lookup(name, box):
    """Places called `name` inside the box, as [[lat, lon, place_rank], …] (best match first)."""
    lon1, lat1, lon2, lat2 = BOXES[box]
    r = requests.get(URL, headers=HEADERS, timeout=30, params={
        "q": name, "format": "jsonv2", "limit": 10, "viewbox": f"{lon1},{lat2},{lon2},{lat1}", "bounded": 1,
        "layer": "address", "accept-language": "el"})
    r.raise_for_status()
    return [[round(float(h["lat"]), 4), round(float(h["lon"]), 4), int(h.get("place_rank") or 0)]
            for h in r.json()
            # places and municipalities, not streets (rank 26+), shops or the whole region
            if h.get("category") in ("place", "boundary") and 12 <= int(h.get("place_rank") or 0) <= 25][:5]


def cached(value):
    """Entries from before candidates were kept ([lat, lon, rank] or None) are looked up again."""
    return isinstance(value, list) and all(isinstance(c, list) for c in value)


def km(a, b):
    return math.hypot((a[0] - b[0]) * 111, (a[1] - b[1]) * 111 * math.cos(math.radians(a[0])))


def area_point(l, geo):
    """The most specific place of the listing that fits with its broader places, or None."""
    box, region = box_for(l), l.get("region") or "Ιωάννινα"
    centre = CENTRES.get(region) if l.get("zone") in (None, "Προάστια") else None
    found = []
    for n in names(l):
        if normalize(n) in (normalize(region), "thessaloniki", "ioannina"):  # no idea where in the city
            continue
        cands = geo.get(f"{box}|{normalize(n)}") or []
        if cands:
            found.append(cands)
    anchors, best = [], None
    for cands in sorted(found, key=lambda cs: min(c[2] for c in cs)):  # broad places first
        if anchors:
            cands = [c for c in cands if min(km(c, a) for a in anchors) <= NEAR_KM]
        elif box == "Θεσσαλονίκη κέντρο":
            cands = [c for c in cands if km(c, centre) <= CITY_KM]
        if not cands:
            continue
        ref = anchors[-1] if anchors else centre
        pick = min(cands, key=lambda c: km(c, ref)) if ref else cands[0]
        anchors.append(pick)
        if best is None or pick[2] >= best[2]:
            best = pick
    return best[:2] if best else None


def check_point(l, point):
    """Whether the listing's own map point can be used; may move it to "Άλλη περιοχή"/"Χαλκιδική"."""
    region, zone = l.get("region") or "Ιωάννινα", l.get("zone")
    if zone == "Εξωτερικό":
        return True
    if not inside(point, "Ελλάδα"):
        return False
    if zone == "Χαλκιδική":
        return inside(point, "Χαλκιδική")
    if zone == "Άλλη περιοχή" or inside(point, region):
        return True
    place = normalize(f"{l.get('area') or ''} {l.get('city') or ''}")
    if any(s in place for s in CITY_STEMS.get(region, ())):
        return False  # says it's in the agency's city, the point says otherwise: trust the words
    l["zone"] = "Χαλκιδική" if region == "Θεσσαλονίκη" and inside(point, "Χαλκιδική") else "Άλλη περιοχή"
    return True


def locate(db, listings, log=print, max_lookups=MAX_LOOKUPS):
    geo = db.setdefault("geo", {})
    # a point that many of one agency's listings share is its office (a map in the page footer)
    shared = Counter((l["site"], tuple(l["coords"])) for l in listings if l.get("coords"))
    per_site = Counter(l["site"] for l in listings if l.get("coords"))
    office = {k for k, n in shared.items() if n >= 4 and n >= 0.2 * per_site[k[0]]}
    for l in listings:
        point = l.get("coords")
        l["exact"] = bool(point and (l["site"], tuple(point)) not in office and check_point(l, point)) or None

    todo = []
    for l in listings:
        box = box_for(l)
        for n in names(l):
            key = f"{box}|{normalize(n)}"
            if not cached(geo.get(key)) and (key, n, box) not in todo:
                todo.append((key, n, box))
    done = 0
    for key, n, box in todo[:max_lookups]:
        try:
            geo[key] = lookup(n, box)  # [] = not found, don't ask again
        except Exception as e:
            log(f"  geo: {n}: {e}")
            break  # service unhappy: try the rest next run
        done += 1
        time.sleep(1.1)
    used = {f"{box_for(l)}|{normalize(n)}" for l in listings for n in names(l)}
    for key in [k for k in geo if k not in used or not cached(geo[k])]:
        del geo[key]  # names no listing uses any more, and old-style entries still waiting

    placed = exact = 0
    for l in listings:
        l["pos"] = l["coords"] if l["exact"] else area_point(l, geo)
        placed += l["pos"] is not None
        exact += bool(l["exact"])
    log(f"geo: {done} place names looked up ({max(0, len(todo) - done)} left), "
        f"{placed} of {len(listings)} listings on the map ({exact} at their own map point)")


def inside(point, box):
    lon1, lat1, lon2, lat2 = BOXES[box]
    return lat1 <= point[0] <= lat2 and lon1 <= point[1] <= lon2
