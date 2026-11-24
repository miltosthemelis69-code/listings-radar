#!/bin/zsh
# Scan the agencies that refuse GitHub's servers ("local": true in sites.json) from this computer
# and save the results to the repo's data branch, next to what GitHub's hourly run saves.
# Installed by launchd (~/Library/LaunchAgents/gr.listings-radar.local-scan.plist) to run hourly
# from its own copy of the repo in ~/.listings-radar/repo. Telegram secrets, if alerts should be
# sent from here, go in ~/.listings-radar/secrets.env (TELEGRAM_BOT_TOKEN=…, TELEGRAM_CHAT_ID=…).
set -e
HOME_DIR="$HOME/.listings-radar"
REPO="miltosthemelis69-code/listings-radar"
ACCOUNT="miltosthemelis69-code"
cd "$HOME_DIR/repo"
echo "== $(date '+%Y-%m-%d %H:%M:%S') local scan"
mkdir "$HOME_DIR/lock" 2>/dev/null || { echo "another scan is still running"; exit 0; }
trap 'rmdir "$HOME_DIR/lock"' EXIT

git checkout -q -- data/listings.json 2>/dev/null || true
git pull -q --ff-only origin main
git fetch -q --depth=1 origin data && git show FETCH_HEAD:listings.json > data/listings.json
if [ -f "$HOME_DIR/secrets.env" ]; then set -a; source "$HOME_DIR/secrets.env"; set +a; fi
.venv/bin/python -m scraper.run --local "$@"

# GitHub's run may have saved in the meantime: keep its agencies, replace only ours
git fetch -q --depth=1 origin data && git show FETCH_HEAD:listings.json > "$HOME_DIR/latest.json"
.venv/bin/python -m scripts.merge_data data/listings.json "$HOME_DIR/latest.json" local
TOKEN="$(/opt/homebrew/bin/gh auth token -h github.com -u "$ACCOUNT")"
rm -rf "$HOME_DIR/push" && mkdir "$HOME_DIR/push" && cp data/listings.json "$HOME_DIR/push/" && cd "$HOME_DIR/push"
git init -q -b data && git add listings.json
git -c user.name=scraper-bot -c user.email=scraper-bot@users.noreply.github.com commit -qm "listings"
git push -fq "https://x-access-token:${TOKEN}@github.com/${REPO}" data
echo "saved to the data branch"
cd "$HOME_DIR/repo" && git checkout -q -- data/listings.json
