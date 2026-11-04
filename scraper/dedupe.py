"""Find the same property listed by several agencies.

Agencies don't share ids, so we match on what they all publish: type, size, price and
place. Two listings from different agencies are the same property when they have the
same city (the agency's region), standard type, size within 1 m² (or 1%), and:
  - both name a specific place (an area or town other than plain "Ιωάννινα") and the
    places agree: price within 3% (agencies sometimes add their commission);
  - one names no specific place: size must match exactly, not be a round number
    (500, 1000 m² plots are everywhere), and price within 1%.
Groups are built greedily from the strongest pairs, and two groups only merge if the
result has one listing per agency and no two members naming different places — so a
listing with no area can't glue together plots from different villages.
Each listing gets `group`, the uid of the group's first-seen member.
"""
from collections import defaultdict

from scraper.common import normalize

# names every listing of a city shares: "Κέντρο" and "Θεσσαλονίκη κέντρο" don't say two flats are the same
GENERIC_PLACES = {"", "ιωαννινα", "ν. ιωαννινων", "υπολοιπες περιοχες", "λοιπες περιοχες", "ηπειρος", "ελλαδα",
                  "κεντρο", "ιστορικο κεντρο", "μακεδονια", "θεσσαλονικη"}


def places(l):
    """Specific place names a listing mentions, normalized: {'κατσικας', 'παμβωτιδα'}."""
    names = [l.get("city") or ""] + (l.get("area") or "").split(",")
    out = {normalize(n).strip() for n in names} - GENERIC_PLACES
    return {n for n in out if not n.startswith("θεσσαλονικη ")}  # "θεσσαλονικη κεντρο", "… περιφ/κοι δημοι"


def places_agree(pa, pb):
    # substring match tolerates "κατσικα" / "κατσικας", "νησι ιωαννινων" / "νησι"
    return any(a in b or b in a for a in pa for b in pb)


def _close(a, b, rel, absolute=0):
    return abs(a - b) <= max(absolute, rel * max(a, b))


def match_score(a, b):
    """None if not the same property; otherwise a sort key (lower = stronger match)."""
    if a["site"] == b["site"] or a.get("type") != b.get("type") or a.get("region") != b.get("region"):
        return None
    if not (a.get("price") and b.get("price") and a.get("sqm") and b.get("sqm")):
        return None
    if not _close(a["sqm"], b["sqm"], 0.01, absolute=1):
        return None
    pa, pb = places(a), places(b)
    price_gap = abs(a["price"] - b["price"]) / max(a["price"], b["price"])
    if pa and pb:
        if not places_agree(pa, pb) or price_gap > 0.03:
            return None
        return (0, price_gap)
    exact = abs(a["sqm"] - b["sqm"]) < 0.5
    round_size = a["sqm"] % 50 == 0 or a["sqm"] % 10 == 0 and a["sqm"] >= 300
    if not exact or round_size or price_gap > 0.01:
        return None
    return (1, price_gap)


def assign_groups(listings):
    """Set listing['group'] on every active listing; returns {group_id: [listings]}."""
    active = [l for l in listings if l.get("active")]
    cluster = {l["uid"]: {"members": [l], "sites": {l["site"]}, "places": [places(l)] if places(l) else []}
               for l in active}
    owner = {l["uid"]: l["uid"] for l in active}

    # candidate pairs: only compare listings of the same type and similar size
    buckets = defaultdict(list)
    for l in active:
        if l.get("sqm") and l.get("price"):
            buckets[(l.get("type"), round(l["sqm"] / 10))].append(l)
    pairs = []
    for (kind, size), members in buckets.items():
        candidates = members + buckets.get((kind, size + 1), [])
        for i, a in enumerate(members):
            for b in candidates[i + 1:]:
                score = match_score(a, b)
                if score is not None:
                    pairs.append((score, a["uid"], b["uid"]))

    for _, ua, ub in sorted(pairs):
        ca, cb = cluster[owner[ua]], cluster[owner[ub]]
        if ca is cb or ca["sites"] & cb["sites"]:
            continue
        if any(not places_agree(p, q) for p in ca["places"] for q in cb["places"]):
            continue  # would put two different named places in one group
        ca["members"] += cb["members"]
        ca["sites"] |= cb["sites"]
        ca["places"] += cb["places"]
        for l in cb["members"]:
            owner[l["uid"]] = owner[ua]

    result = {}
    for uid in {owner[u] for u in owner}:
        members = sorted(cluster[uid]["members"], key=lambda l: (l["first_seen"], l["uid"]))
        gid = members[0]["uid"]
        for l in members:
            l["group"] = gid
        result[gid] = members
    for l in listings:
        if not l.get("active"):
            l.pop("group", None)
    return result
