# Listings Radar

Scrapes local real estate agency sites into one dashboard and sends Telegram alerts
for new listings matching your saved searches. Runs entirely on free tiers.
**Properties for sale only**: rentals are filtered at the site where possible
(`params` in sites.json) and dropped by the runner otherwise. **Only these types are kept**
(`KEEP_TYPES` in `scraper/common.py`): Διαμέρισμα, Studio/Γκαρσονιέρα, Γραφείο, Κτίριο,
Βιοτεχνικός χώρος, Βιομηχανικός χώρος. Plots, houses, villas, maisonettes, shops and the rest are dropped.

- `sites.json` – agencies to scrape (id, name, adapter, base_url, optional `params`)
- `scraper/adapters/` – one module per site platform:
  - `realstatus.py` – sites built on the realstatus.gr CRM (gikaispiti.gr)
  - `realstatus_v2.py` – newer realstatus.gr template (38400.gr, RE/MAX Premier)
  - `wpl.py` – WordPress + Realtyna WPL plugin (oikiarealestate.gr). Supports
    `full_scan_hours` for slow servers: runs in between read only the newest pages
  - `osproperty.py` – Joomla + OS Property component (ioanninahome.gr, house4you.gr)
  - `houzez.py` – WordPress + Houzez theme, via its JSON API (ioanninacasa.gr, gartzonikashome.gr,
    mesitikogeorgiou.gr — older Houzez, price/size read from the status pages)
  - `eagents.py` – e-agents workspace platform (polisestate.gr, greekestate.eu, skourashome.gr)
  - `wapp.py` – sites built by wapp.gr (elite-realestate.gr)
  - `vrespiti.py` – vrespiti.gr (custom ASP site)
  - `gethouse.py` – gethouse.gr / re1.gr platform (gethouse.gr)
  - `estateplus.py` – estateplus.gr platform (domus-estate.gr, foititikaspitia.eu)
  - `myhome.py` – WordPress + MyHome theme, via its JSON API (housecity.gr)
  - `orbit.py` – orbit.gr platform (realhouses.gr)
- Two cities: each site in sites.json has a `region` ("Ιωάννινα" by default, "Θεσσαλονίκη"); the
  dashboard has a City filter and saved searches can set `"region"`. Thessaloniki agencies and
  why some couldn't be added: `THESSALONIKI_AGENCIES.md` (rebuild with `python -m scripts.thess_report`)
- More adapters were added for Thessaloniki (abroker, spitogatos_sites, realhomes, wpresidence,
  realstatus_v3/_seo, estateplus_v2/_pxp and site-specific ones); each file's docstring says which sites
- `scripts/try_site.py` tests one site config without touching the data; `scripts/fingerprint.py`
  guesses a site's platform
- Sites are scraped in parallel (16 at a time, 1s between requests to the same site)
- Property types and place names are standardised across agencies (`canonical_type`, `fix_place_spelling`)
- `scraper/details.py` – floor and elevator for flats, studios, maisonettes, offices and shops,
  read once from each listing's own page (only new listings cost a request after that).
  `floor`: -1 basement, 0 ground, 0.5 mezzanine, 1, 2, …; `elevator`: true / false / null (not stated).
  Saved searches can use `min_floor`, `max_floor` and `"elevator": true`
- `scraper/dedupe.py` – the same property listed by several agencies gets one `group` id
  (matched on type, size, price and place). The dashboard shows one card per property with
  a link to every agency; alerts go out once per property, and not at all when an agency
  adds a property another agency already listed
- Rented/sold listings that agencies keep online are skipped
- Saved searches with a bedroom minimum still match listings whose site doesn't publish bedrooms
- `scraper/zones.py` – marks listings outside the agency's own area (`zone`: "Προάστια",
  "Χαλκιδική", "Εξωτερικό", "Άλλη περιοχή"). For Thessaloniki only the city itself (Δήμος
  Θεσσαλονίκης: Κέντρο, Τούμπα, Χαριλάου, Ανάληψη, Φάληρο, Άνω Πόλη …) counts; Καλαμαριά, Πυλαία,
  Θέρμη, Σταυρούπολη, Πολίχνη, Συκιές and the other municipalities are "Προάστια". Agencies also sell
  holiday homes in Χαλκιδική, on islands, in Athens and Cyprus. The dashboard hides all of these
  unless "Include Thessaloniki suburbs" / "Include Χαλκιδική, abroad & other regions" is ticked;
  saved searches skip them unless they set `"include_suburbs": true` / `"include_outside": true`
- `scraper/geo.py` – map positions: each area name is looked up once on OpenStreetMap's Nominatim
  (cached in the data file's "geo" table, at most 150 new names per run), so pins mark the
  neighbourhood, not the building. `scripts/geocode_backlog.py` looks up everything at once
- `preferences.json` – saved searches that trigger Telegram alerts (or the `PREFERENCES_JSON`
  secret, so they stay private on a public repo)
- `data/listings.json` – all listings with first seen, price history, active flag, in a compact
  form (`scraper/store.py`: no repeated or empty fields; removed listings kept 30 days)
- `index.html` – static dashboard (reads `data/listings.json`)
- `.github/workflows/scrape.yml` – hourly scrape on GitHub Actions. Listings are kept on a
  `data` branch with a single commit (force-pushed, so no history builds up) and the
  dashboard is published to GitHub Pages

Run locally:

    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/python -m scraper.run          # scrape + alert
    .venv/bin/python -m scraper.run --full   # force a full scan of every site
    python3 -m http.server 8765              # dashboard at http://localhost:8765

Alerts: set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (env vars locally, repo secrets on GitHub).
Without them, matching alerts are printed to the console instead. A site's first scrape never alerts.

Not supported:
- Imperva bot protection blocks automated access: estateland.gr, e-mesitiki.gr,
  nexthome.gr, ktimatomesitikiioanninon.gr, rebs.gr, anyland.gr, mesitikaioan.gr,
  easystate.gr, spiti24.gr (aggregator, part of Spitogatos)
- Sites that don't load: realestatepantas.gr, akinito24.gr, basilisgeorgiou.gr
- igoumenidis.gr: a builder's 2011 project portfolio, not current listings
- re1.gr: national network whose location tags are wrong (Volos listings tagged Ioannina)
- value4greece.com: listing pages repeat the same 26 results; would need per-listing
  scraping via its sitemap, and most of its ~300 sales are outside Ioannina
