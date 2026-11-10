import html
import os

import requests

from scraper.common import normalize


def matches(listing, pref):
    # Thessaloniki suburbs, Χαλκιδική, abroad and other regions only when a search asks for them (zones.py)
    if listing.get("zone") == "Προάστια" and not pref.get("include_suburbs"):
        return False
    if listing.get("zone") not in (None, "Προάστια") and not pref.get("include_outside"):
        return False
    if pref.get("deal") and listing.get("deal") != pref["deal"]:
        return False
    # both cities have a "Κέντρο", so a search can be pinned to one: "region": "Θεσσαλονίκη"
    if pref.get("region") and normalize(listing.get("region") or "Ιωάννινα") != normalize(pref["region"]):
        return False
    if pref.get("types") and not any(normalize(t) in normalize(listing.get("type")) for t in pref["types"]):
        return False
    # some sites have no per-listing location, so the area is often only in the description
    where = normalize(f"{listing.get('location')} {listing.get('description')}")
    if pref.get("locations") and not any(normalize(l) in where for l in pref["locations"]):
        return False
    for field, key, op in [
        ("price", "min_price", "min"), ("price", "max_price", "max"),
        ("sqm", "min_sqm", "min"), ("sqm", "max_sqm", "max"),
        ("bedrooms", "min_bedrooms", "min"),
        ("floor", "min_floor", "min"), ("floor", "max_floor", "max"),
    ]:
        limit = pref.get(key)
        if limit is None:
            continue
        value = listing.get(field)
        if value is None:
            if field in ("bedrooms", "floor"):  # not every listing states these; alert rather than miss it
                continue
            return False
        if (op == "min" and value < limit) or (op == "max" and value > limit):
            return False
    # "elevator": true skips only listings that say they have none; unstated still matches.
    # "elevator": "required" also skips listings that don't mention one (like the dashboard's "Yes")
    if pref.get("elevator") is True and listing.get("elevator") is False:
        return False
    if pref.get("elevator") == "required" and listing.get("elevator") is not True:
        return False
    return True


def eur(n):
    return f"€{n:,}".replace(",", ".") if n else "Price on request"


def format_message(members, pref_name):
    """One message per property, with a link for every agency that lists it."""
    listing = members[0]
    detail = max(members, key=lambda m: len(m.get("location") or ""))  # most specific place
    beds = next((m["bedrooms"] for m in members if m.get("bedrooms")), None)
    parts = [
        ("🔁 Back on the market\n" if listing.get("relisted_at") else "")
        + f"🏠 <b>{html.escape(listing.get('type') or listing['title'])}"
        + (f" {listing['sqm']:g} m²" if listing.get("sqm") else "") + "</b>",
        f"💶 {eur(listing.get('price'))}",
        f"📍 {html.escape(detail.get('location') or '-')}",
    ]
    if beds:
        parts.append(f"🛏 {beds} bedroom{'s' if beds != 1 else ''}")
    floor = next((m["floor"] for m in members if m.get("floor") is not None), None)
    lift = True if any(m.get("elevator") is True for m in members) else \
        False if any(m.get("elevator") is False for m in members) else None
    if floor is not None or lift is not None:
        names = {-1: "basement", 0: "ground floor", 0.5: "mezzanine", 1: "1st floor", 2: "2nd floor", 3: "3rd floor"}
        bits = [names.get(floor, f"{floor:g}th floor")] if floor is not None else []
        bits += ["elevator"] if lift else ["no elevator"] if lift is False else []
        parts.append("🏢 " + " · ".join(bits))
    parts.append(f"🔎 matches “{html.escape(pref_name)}”")
    parts.append("")
    parts.append("Listed by:" if len(members) > 1 else "Listed by")
    for m in sorted(members, key=lambda m: m.get("price") or 0):
        price = f" · {eur(m['price'])}" if len(members) > 1 and m.get("price") else ""
        parts.append(f'• <a href="{html.escape(m["url"])}">{html.escape(m["site_name"])}</a>{price}')
    return "\n".join(parts)


def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("  (telegram not configured, would send):\n" + text + "\n")
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=30,
    )
    r.raise_for_status()


def notify_new(new_properties, preferences):
    """new_properties: one list of listings per property (the agencies that list it)."""
    sent = 0
    for members in new_properties:
        for pref in preferences:
            if any(matches(m, pref) for m in members):
                send_telegram(format_message(members, pref.get("name", "saved search")))
                sent += 1
                break  # one message per property even if several searches match
    return sent
