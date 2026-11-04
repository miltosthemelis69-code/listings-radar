"""Guess each candidate site's platform so it can go to the right adapter.

Usage: .venv/bin/python -m scripts.fingerprint candidates/merged.json candidates/fingerprints.json
Reads {"agencies": [{"name", "website", ...}]}, fetches each homepage once (in parallel,
one request per site) and writes the same list with "platform", "status" and "evidence".
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

from scraper.common import USER_AGENT

# (platform, regex on homepage HTML) — first match wins; bot walls are checked first
SIGNATURES = [
    ("blocked:imperva", r"Pardon Our Interruption|_Incapsula_Resource|reese84"),
    ("blocked:cloudflare", r"cf-chl|challenge-platform|Just a moment\.\.\.|Attention Required! \| Cloudflare"),
    ("blocked:captcha", r"g-recaptcha|hcaptcha\.com/1/api|captcha-delivery|datadome"),
    ("eagents", r"e-agents\.gr|e-agents\.cloud|e-agents workspace"),
    ("realstatus_v2", r"listings_async|/listings/category/"),
    ("realstatus", r"realstatus\.gr|results\.php\?"),
    ("estateplus", r"estateplus\.gr|kf_listing_outer_wrap|kf_advacnce_search"),
    ("orbit", r"orbit\.gr|property_detail/\d+"),
    ("wpl", r"real-estate-listing-realtyna|wpl_prp_cont|wplpage"),
    ("houzez", r"wp-content/themes/houzez"),
    ("myhome", r"wp-content/themes/myhome"),
    ("osproperty", r"com_osproperty|osproperty"),
    ("wapp", r"wapp\.gr|estate_box"),
    ("gethouse", r"/image/\d+/thumb/|/properties/sales\?"),
    ("vrespiti-like", r"pdetails\?|search\.asp\?"),
    ("spitogatos-platform", r"/el/akinita/anazitisi|/akinita/anazitisi\?"),
    ("wordpress-other", r"wp-content/themes/([a-z0-9_-]+)"),
    ("joomla-other", r"/components/com_|Joomla!"),
    ("nextjs", r"__NEXT_DATA__|/_next/static"),
    ("nuxt", r"__NUXT__|/_nuxt/"),
]


def probe(agency):
    url = agency.get("website")
    if not url:
        return {**agency, "platform": None, "status": "no website", "evidence": ""}
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "el-GR,el;q=0.9"},
                         timeout=25, allow_redirects=True)
    except requests.RequestException as e:
        return {**agency, "platform": None, "status": "dead", "evidence": type(e).__name__}
    html = r.text
    for platform, pattern in SIGNATURES:
        # contact forms carry reCAPTCHA too; it's only a wall when the page is just the challenge
        if platform == "blocked:captcha" and len(html) > 20000:
            continue
        m = re.search(pattern, html, re.I)
        if m:
            evidence = m.group(1) if m.groups() else m.group(0)
            break
    else:
        platform, evidence = "unknown", ""
    status = "ok" if r.ok else f"http {r.status_code}"
    if platform.startswith("blocked") or platform == "spitogatos-platform" and len(html) < 5000:
        status = "blocked"
    title = re.search(r"<title[^>]*>([^<]{0,90})", html, re.I)
    return {**agency, "final_url": r.url, "platform": platform, "status": status, "evidence": evidence,
            "title": title.group(1).strip() if title else "", "bytes": len(html)}


def main():
    src, dst = sys.argv[1], sys.argv[2]
    agencies = json.load(open(src))["agencies"]
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(probe, agencies))
    json.dump({"agencies": results}, open(dst, "w"), ensure_ascii=False, indent=1)
    from collections import Counter
    print(Counter(r["platform"] for r in results).most_common())
    print(Counter(r["status"] for r in results).most_common())


if __name__ == "__main__":
    main()
