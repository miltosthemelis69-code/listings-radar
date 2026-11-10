"""Forward the property portals' own alert emails to Telegram.

Agencies behind bot protection (Imperva) can't be scanned, but they list on Spitogatos and
xe.gr, which email you new matches for a saved search for free. Each run reads those alert
emails from your inbox over IMAP (read-only: nothing is marked, moved or deleted), pulls the
listings out of them and sends each one to Telegram once. The portals' sites are never
visited; the links in the message are for you to open.

Needs ALERT_EMAIL and ALERT_EMAIL_APP_PASSWORD (a Gmail app password, not your normal
password); ALERT_IMAP_HOST if the mailbox isn't Gmail. Without them this does nothing.
Listings seen are kept in the data file's "mail_seen" table so none is sent twice.
"""
import email
import html
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from urllib.parse import unquote

from bs4 import BeautifulSoup

from scraper.common import parse_price, parse_sqm
from scraper.notify import eur, send_telegram

DAYS = 4            # emails this old or newer are read every run
KEEP_SEEN_DAYS = 60
PORTALS = {
    # sender search, listing link pattern (group 1 = the portal's listing id)
    "Spitogatos": ("spitogatos", re.compile(r"spitogatos\.gr/(?:[a-z]{2}/)?(?:aggelia|ad|listing)/?(?:[^\"'\s]*?)(\d{6,})")),
    "xe.gr": ("xe.gr", re.compile(r"xe\.gr/(?:[a-z]{2}/)?property/(?:d/)?[^\"'\s]*?(\d{6,})")),
}


def _decode(value):
    return str(make_header(decode_header(value or "")))


def _html(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            return "<br>".join(html.escape(line) for line in text.splitlines())
    return ""


def listings_in(body, pattern):
    """[{id, url, text}] for each listing linked in an alert email, with the text around it."""
    soup = BeautifulSoup(body, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        href = unquote(unquote(a["href"]))  # links are often wrapped in a click-tracking redirect
        m = pattern.search(href)
        if not m or m.group(1) in found:
            continue
        # climb to the smallest block around the link that has a price in it: the listing's card
        block, text = a, a.get_text(" ", strip=True)
        for _ in range(6):
            if block.parent is None:
                break
            block = block.parent
            text = block.get_text(" ", strip=True)
            if "€" in text and len(text) > 20:
                break
        found[m.group(1)] = {"id": m.group(1), "url": a["href"], "text": re.sub(r"\s+", " ", text)[:400]}
    return list(found.values())


def describe(item):
    """Price, size and a short title from the text of a listing's card."""
    t = item["text"]
    price = re.search(r"(\d{1,3}(?:[.,]\d{3})+|\d{4,})\s*€|€\s*(\d{1,3}(?:[.,]\d{3})+|\d{4,})", t)
    sqm = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:τ\.?\s?μ\.?|m²|m2|τμ)", t, re.I)
    return {
        "price": parse_price(price.group(1) or price.group(2)) if price else None,
        "sqm": parse_sqm(sqm.group(1)) if sqm else None,
        "title": t[:160],
    }


def wanted(info, preferences):
    """The portal's saved search already filters; this only drops what is clearly outside every search."""
    for pref in preferences:
        ok = True
        for field, low, high in (("price", "min_price", "max_price"), ("sqm", "min_sqm", "max_sqm")):
            v = info[field]
            if v is not None and ((pref.get(low) and v < pref[low]) or (pref.get(high) and v > pref[high])):
                ok = False
        if ok:
            return True
    return not preferences


def message(portal, info, url, subject):
    head = "🏠 <b>" + html.escape(f"{info['sqm']:g} m²" if info["sqm"] else "New listing") + "</b>"
    return "\n".join([
        f"📬 From your {portal} alert",
        head,
        f"💶 {eur(info['price'])}",
        f"📝 {html.escape(info['title'])}",
        f"✉️ {html.escape(subject[:120])}",
        "",
        f'• <a href="{html.escape(url)}">Open on {portal}</a>',
    ])


def forward(db, preferences, log=print):
    user, password = os.environ.get("ALERT_EMAIL"), os.environ.get("ALERT_EMAIL_APP_PASSWORD")
    if not user or not password:
        return 0
    seen = db.setdefault("mail_seen", {})
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=KEEP_SEEN_DAYS)).date().isoformat()
    for key in [k for k, day in seen.items() if day < cutoff]:
        del seen[key]
    since = (now - timedelta(days=DAYS)).strftime("%d-%b-%Y")
    sent = 0
    box = imaplib.IMAP4_SSL(os.environ.get("ALERT_IMAP_HOST") or "imap.gmail.com")
    try:
        box.login(user, password)
        box.select("INBOX", readonly=True)
        for portal, (sender, pattern) in PORTALS.items():
            _, data = box.search(None, "SINCE", since, "FROM", f'"{sender}"')
            ids = data[0].split()
            new = 0
            for num in ids:
                _, parts = box.fetch(num, "(BODY.PEEK[])")
                msg = email.message_from_bytes(parts[0][1])
                subject = _decode(msg.get("Subject"))
                items = listings_in(_html(msg), pattern)
                key = f"{portal}:email:{msg.get('Message-ID') or num.decode()}"
                if not items and key not in seen:
                    # a format we can't read listings from: still say an alert came in
                    seen[key] = now.date().isoformat()
                    send_telegram(f"📬 New {portal} alert email\n✉️ {html.escape(subject[:200])}\n\nOpen it in your inbox.")
                    new += 1
                for item in items:
                    key = f"{portal}:{item['id']}"
                    if key in seen:
                        continue
                    seen[key] = now.date().isoformat()
                    info = describe(item)
                    if not wanted(info, preferences):
                        continue
                    send_telegram(message(portal, info, item["url"], subject))
                    new += 1
            log(f"mail alerts: {portal}: {len(ids)} emails in the last {DAYS} days, {new} new listings sent")
            sent += new
    except (imaplib.IMAP4.error, OSError) as e:
        log(f"mail alerts: could not read the inbox: {e}")
    finally:
        try:
            box.logout()
        except Exception:
            pass
    return sent


def check():
    """For the test run: can we read the inbox, and how many portal alert emails are there?"""
    user, password = os.environ.get("ALERT_EMAIL"), os.environ.get("ALERT_EMAIL_APP_PASSWORD")
    if not user or not password:
        return "📭 Portal email alerts: not set up (ALERT_EMAIL / ALERT_EMAIL_APP_PASSWORD missing)."
    since = (datetime.now(timezone.utc) - timedelta(days=DAYS)).strftime("%d-%b-%Y")
    try:
        box = imaplib.IMAP4_SSL(os.environ.get("ALERT_IMAP_HOST") or "imap.gmail.com")
        box.login(user, password)
        box.select("INBOX", readonly=True)
        lines = []
        for portal, (sender, pattern) in PORTALS.items():
            _, data = box.search(None, "SINCE", since, "FROM", f'"{sender}"')
            ids = data[0].split()
            listings = 0
            for num in ids:
                _, parts = box.fetch(num, "(BODY.PEEK[])")
                listings += len(listings_in(_html(email.message_from_bytes(parts[0][1])), pattern))
            lines.append(f"• {portal}: {len(ids)} emails in the last {DAYS} days, {listings} listings read from them")
        box.logout()
        return "📬 Inbox connected.\n" + "\n".join(lines)
    except (imaplib.IMAP4.error, OSError) as e:
        return f"⚠️ Could not read the inbox: {html.escape(str(e))[:200]}"


if __name__ == "__main__":
    text = check()
    print(text)
    send_telegram(text)
