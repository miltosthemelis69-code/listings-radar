"""Read and write data/listings.json in a compact form.

The file is read by the dashboard on every visit and rewritten every hour, so it only
keeps what can't be worked out again:
- no fields that repeat the key or the agency: uid, site, source_id, site_name, region
  (the agency's name and city are in "sites"), no `location` (it is area + city)
- no empty values, `active` only when false, `last_seen` only for removed listings,
  `group` only when shared, `price_history` only after a price change
- descriptions are cut to 300 characters (they are only searched, never shown)
- removed listings are dropped 30 days after they disappeared
index.html undoes the same steps in `unpack()`.
"""
import json
from datetime import datetime, timedelta

FORMAT = 2
DESCRIPTION_CHARS = 300
KEEP_REMOVED_DAYS = 30
DERIVED = {"uid", "site", "source_id", "site_name", "region", "location", "deal"}


def pack_listing(uid, l):
    out = {}
    for k, v in l.items():
        if k in DERIVED or v is None or v == "" or v == []:
            continue
        out[k] = v
    if l.get("active", True):
        out.pop("active", None)
        out.pop("last_seen", None)
    if out.get("group") == uid:
        del out["group"]
    if out.get("price_history") == [[l.get("first_seen"), l.get("price")]]:
        del out["price_history"]
    for k in ("details_checked", "coords_checked"):
        if out.get(k):
            out[k] = out[k][:10]
    if out.get("description"):
        out["description"] = out["description"][:DESCRIPTION_CHARS]
    return out


def unpack_listing(uid, rec, sites, updated_at):
    site, source_id = uid.split(":", 1)
    info = sites.get(site, {})
    l = {"uid": uid, "site": site, "source_id": source_id, "site_name": info.get("name", site),
         "region": info.get("region", "Ιωάννινα"), "deal": "sale", "active": True, **rec}
    for k in ("city", "area", "title", "description", "type"):
        l.setdefault(k, "")
    for k in ("price", "sqm", "bedrooms", "code", "image", "url", "floor", "elevator", "group"):
        l.setdefault(k, None)
    l["group"] = l["group"] or uid
    l.setdefault("last_seen", updated_at)
    l.setdefault("price_history", [[l.get("first_seen"), l.get("price")]])
    l["location"] = ", ".join(x for x in [l["area"], l["city"]] if x)
    return l


def load(path):
    if not path.exists():
        return {"updated_at": None, "sites": {}, "listings": {}}
    db = json.loads(path.read_text(encoding="utf-8"))
    if db.get("format") != FORMAT:  # older, uncompressed file: already complete
        return db
    db["listings"] = {uid: unpack_listing(uid, rec, db["sites"], db["updated_at"])
                      for uid, rec in db["listings"].items()}
    return db


def save(path, db):
    cutoff = (datetime.fromisoformat(db["updated_at"]) - timedelta(days=KEEP_REMOVED_DAYS)).isoformat()
    listings = {uid: pack_listing(uid, l) for uid, l in db["listings"].items()
                if l.get("active", True) or (l.get("last_seen") or "") >= cutoff}
    out = {"format": FORMAT, "updated_at": db["updated_at"], "sites": db["sites"], "geo": db.get("geo", {}),
           "mail_seen": db.get("mail_seen", {}), "listings": listings}
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
