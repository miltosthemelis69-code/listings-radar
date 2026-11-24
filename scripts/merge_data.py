"""Combine two copies of listings.json: one side's agencies from `mine`, the rest from `theirs`.

GitHub scans most agencies and the owner's computer scans the ones marked "local" in
sites.json; both save to the same `data` branch. Right before saving, each side fetches the
branch again and keeps the other side's agencies from it, so neither overwrites the other.

Usage: python -m scripts.merge_data <mine.json> <theirs.json> local|github   (writes mine.json)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def merge(mine, theirs, side):
    local = {s["id"] for s in json.loads((ROOT / "sites.json").read_text(encoding="utf-8")) if s.get("local")}
    owns = (lambda site: site in local) if side == "local" else (lambda site: site not in local)
    if mine.get("format") != theirs.get("format"):
        return mine  # the other copy is from an older version: nothing safe to take from it
    out = dict(mine)
    out["listings"] = {u: l for u, l in theirs["listings"].items() if not owns(u.split(":", 1)[0])}
    out["listings"].update({u: l for u, l in mine["listings"].items() if owns(u.split(":", 1)[0])})
    out["sites"] = {k: v for k, v in theirs["sites"].items() if not owns(k)}
    out["sites"].update({k: v for k, v in mine["sites"].items() if owns(k)})
    out["geo"] = {**theirs.get("geo", {}), **mine.get("geo", {})}
    out["mail_seen"] = (theirs if side == "local" else mine).get("mail_seen", {})  # portal emails are read on GitHub
    out["updated_at"] = max(mine["updated_at"], theirs["updated_at"])
    return out


if __name__ == "__main__":
    mine_path, theirs_path, side = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    mine, theirs = (json.loads(p.read_text(encoding="utf-8")) for p in (mine_path, theirs_path))
    out = merge(mine, theirs, side)
    mine_path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"merged ({side}): {len(out['listings'])} listings, {len(out['sites'])} agencies")
