"""Build THESSALONIKI_AGENCIES.md: every Thessaloniki-city agency found, added or not, and why."""
import json
import re
from collections import Counter
from pathlib import Path

from scraper import store
from scraper.common import normalize


def domain(u):
    h = re.sub(r"^https?://", "", u or "").split("/")[0].lower()
    return h[4:] if h.startswith("www.") else h


fp = {a["domain"]: a for a in json.load(open("candidates/fingerprints.json"))["agencies"]}
sites = [s for s in json.load(open("sites.json")) if s.get("region") == "Θεσσαλονίκη"]
db = store.load(Path("data/listings.json"))
counts = Counter(l["site"] for l in db["listings"].values() if l["active"])
added = {}
for s in sites:
    added[domain(s["base_url"])] = s
redirects = {"plrealestate.gr": "acb.gr", "celestproperties.gr": "verorealestate.gr"}

# reasons from the builder agents and my own tests
reasons = {}
for tag in ["fonts", "spitogatos", "js", "custom", "wp", "realstatus"]:
    for r in json.load(open(f"candidates/build_{tag}.json"))["results"]:
        if r["status"] != "added":
            reasons[domain(r["domain"])] = r["reason"]
for r in json.load(open("candidates/supported_results.json")):
    d = r["domain"]
    if d in ("aspis-realestate.gr", "kwgreece.gr"):
        reasons[d] = "National network site, can't be limited to the Thessaloniki office (KW North is added separately)"
manual = {
    "forumland.gr": "Not in Thessaloniki city (Καλαμαριά)",
    "imaginelife.gr": "Not in Thessaloniki city (Μενεμένη)",
    "tk-realestate.com": "Not in Thessaloniki city (Εύοσμος)",
}


def short(reason):
    """Agents wrote long reasons; keep the table readable."""
    r = reason.lower()
    for key, text in [("not in thessaloniki", "Not in Thessaloniki (Attica)"), ("no listings for sale", "No properties for sale on the site"),
                      ("no listings on own site", "No listings on its own site (only a Spitogatos profile)"),
                      ("javascript", "Listings only load through JavaScript"), ("postback", "Old ASP.NET site, pages only through form postbacks"),
                      ("no place names", "Listings have no location, so they can't be placed"), ("national site", "International portal, no Thessaloniki office to filter on"),
                      ("502", "Website error (HTTP 502)"), ("503", "Website error (HTTP 503)")]:
        if key in r:
            return text
    return reason


def reason_for(d, a):
    if d in reasons:
        return short(reasons[d])
    if d in manual:
        return manual[d]
    p, st = a.get("platform") or "", a.get("status")
    if p == "blocked:imperva":
        return "Bot protection (Imperva) blocks automated access"
    if p.startswith("blocked"):
        return "Bot protection blocks automated access"
    if st == "dead":
        return "Website doesn't load"
    if st and st.startswith("http"):
        return f"Website error ({st.upper()})"
    return "Not added"


rows = []
for d, a in sorted(fp.items(), key=lambda kv: normalize(kv[1]["name"])):
    if d in manual:  # turned out to be outside the city: not part of this list
        continue
    if d in redirects.values() and any(new in fp for new, old in redirects.items() if old == d):
        continue  # old domain of an agency already listed under its new one
    s = added.get(d) or added.get(domain(a.get("final_url")))
    if not s:
        for new, old in redirects.items():
            if d == old and new in added:
                s = added[new]
    if s:
        rows.append((a["name"], d, True, counts.get(s["id"], 0), ""))
    else:
        rows.append((a["name"], d, False, None, reason_for(d, a)))

ok = [r for r in rows if r[2]]
lines = [
    "# Thessaloniki real estate agencies",
    "",
    f"{len(rows)} agencies based in the city of Thessaloniki with a website were found. "
    f"**{len(ok)} added** ({sum(r[3] for r in ok):,} listings for sale), **{len(rows) - len(ok)} not added**.",
    "",
    "| # | Agency | Website | Added | Listings | Why not |",
    "|---|---|---|:---:|---:|---|",
]
for i, (name, d, is_ok, n, why) in enumerate(rows, 1):
    lines.append(f"| {i} | {name} | {d} | {'✅' if is_ok else '❌'} | {n if is_ok else ''} | {why} |")
why = Counter(r[4] for r in rows if not r[2])
lines += ["", "## Why agencies couldn't be added", "", "| Reason | Agencies |", "|---|---:|"]
lines += [f"| {k} | {v} |" for k, v in why.most_common()]
open("THESSALONIKI_AGENCIES.md", "w").write("\n".join(lines) + "\n")
print(len(rows), "agencies,", len(ok), "added,", sum(r[3] for r in ok), "listings")
for k, v in why.most_common():
    print(f"  {v:3}  {k}")
