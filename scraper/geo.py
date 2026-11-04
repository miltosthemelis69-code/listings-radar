"""Map positions for listings.

Most agency pages embed the property's own map point (read by details.py into `coords`);
that is used when it lies in the listing's area and isn't the agency's office (a point
shared by many of its listings). Otherwise the listing is placed at its area: each place name ("Κάτω Τούμπα", "Νέα Κρήνη", "Πευκοχώρι") is looked up once on
OpenStreetMap's free Nominatim service and kept in the data file's "geo" table, so a normal
run only looks up names it hasn't seen (at most MAX_LOOKUPS, 1 per second, as Nominatim asks).
Searches are limited to a box around the listing's area so "Άγιος Ιωάννης" lands in
Kalamaria, not Crete. A listing is placed at its most specific name that was found
(Nominatim's place_rank: a neighbourhood beats a town, a town beats the city); those pins
show the neighbourhood, not the building (`exact` is not set).
"""
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
    "Θεσσαλονίκη": (22.55, 40.35, 23.95, 41.05),
    "Χαλκιδική": (22.95, 39.9, 24.45, 40.65),
    "Ιωάννινα": (19.9, 38.5, 21.7, 40.45),
    "Ελλάδα": (19.3, 34.7, 29.7, 41.8),
}
GENERIC = {"κεντρο", "center", "centre", "επεκταση", "γενικα", "περιφ", "κοι δημοι", "προαστια", "suburbs",
           "περιχωρα", "υπολοιπες περιοχες", "λοιπες χωρες", "βορεια ελλαδα", "κεντρικη ελλαδα", "μακεδονια"}


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
    lon1, lat1, lon2, lat2 = BOXES[box]
    r = requests.get(URL, headers=HEADERS, timeout=30, params={
        "q": name, "format": "jsonv2", "limit": 1, "viewbox": f"{lon1},{lat2},{lon2},{lat1}", "bounded": 1,
        "layer": "address", "accept-language": "el"})  # places and streets, not churches named Άγιος Ιωάννης
    r.raise_for_status()
    hits = r.json()
    if not hits:
        return None
    h = hits[0]
    return [round(float(h["lat"]), 4), round(float(h["lon"]), 4), int(h.get("place_rank") or 0)]


def locate(db, listings, log=print, max_lookups=MAX_LOOKUPS):
    geo = db.setdefault("geo", {})
    todo = []
    for l in listings:
        box = box_for(l)
        for n in names(l):
            key = f"{box}|{normalize(n)}"
            if key not in geo and (key, n, box) not in todo:
                todo.append((key, n, box))
    done = 0
    for key, n, box in todo[:max_lookups]:
        try:
            geo[key] = lookup(n, box)  # None = not found, don't ask again
        except Exception as e:
            log(f"  geo: {n}: {e}")
            break  # service unhappy: try the rest next run
        done += 1
        time.sleep(1.1)
    # a point that many of one agency's listings share is its office (a map in the page footer)
    shared = Counter((l["site"], tuple(l["coords"])) for l in listings if l.get("coords"))
    per_site = Counter(l["site"] for l in listings if l.get("coords"))
    office = {k for k, n in shared.items() if n >= 4 and n >= 0.2 * per_site[k[0]]}
    placed = exact = 0
    for l in listings:
        box = box_for(l)
        point = l.get("coords")
        if point and (l["site"], tuple(point)) not in office and inside(point, "Θεσσαλονίκη" if box == "Θεσσαλονίκη κέντρο" else box):
            l["pos"], l["exact"] = point, True
            placed += 1
            exact += 1
            continue
        l["exact"] = None
        best = None
        for n in names(l):
            if normalize(n) in (normalize(l.get("region")), "thessaloniki", "ioannina"):  # no idea where in the city
                continue
            hit = geo.get(f"{box}|{normalize(n)}")
            if hit and (best is None or hit[2] > best[2]):
                best = hit
        l["pos"] = best[:2] if best else None
        placed += best is not None
    log(f"geo: {done} place names looked up ({max(0, len(todo) - done)} left), "
        f"{placed} of {len(listings)} listings on the map ({exact} at their own map point)")


def inside(point, box):
    lon1, lat1, lon2, lat2 = BOXES[box]
    return lat1 <= point[0] <= lat2 and lon1 <= point[1] <= lon2
