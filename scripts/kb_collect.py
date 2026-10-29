#!/usr/bin/env python3
"""Killboard collector — pulls the USF "Pidrakhuyka" killboard via its public API
and writes data/killboard_monthly.csv (one row per unit-month, latest snapshot).

No key needed. Endpoints:
  GET https://sbs-group.army/api/public/subdivisions                  -> all subdivisions
  GET https://sbs-group.army/api/public/subdivisions/<subId>          -> unit detail incl. periods
  GET https://sbs-group.army/api/public/statistics/<subId>/<periodId> -> stats for a unit-period

Only monthly periods are published here; the latest raw JSON per unit-month is kept
under data/raw/ (git history preserves prior snapshots). Stdlib only — runs on a bare
GitHub Actions runner. Any network/shape failure exits non-zero so the weekly workflow
fails loudly instead of committing stale data.
"""
import csv
import json
import os
import sys
import time
import urllib.request

BASE = "https://sbs-group.army/api/public"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(DATA, "raw")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://sbs-group.army/en/",
}

N_TC = 43  # target classes tc01..tc43; a new class appearing is a schema change we want to notice


def get(url, retries=4):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            if i == retries - 1:
                raise RuntimeError(f"GET {url} failed after {retries} tries: {e}")
            time.sleep(3 * (i + 1))


def main():
    os.makedirs(RAW, exist_ok=True)
    subs = get(f"{BASE}/subdivisions")["data"]["subdivisions"]
    if len(subs) < 10:
        raise RuntimeError(f"only {len(subs)} subdivisions returned — API shape changed?")
    print(f"{len(subs)} subdivisions")

    rows = []
    max_tc = 0
    for s in subs:
        sid = s["id"]
        name = s.get("title_en") or s.get("title")
        detail = get(f"{BASE}/subdivisions/{sid}")
        for p in detail["data"]["subdivision"].get("periods", []):
            ptype = str(p.get("periodType", ""))
            if not ptype.startswith("monthly"):
                continue
            st = get(f"{BASE}/statistics/{sid}/{p['id']}")
            time.sleep(0.25)
            if not st.get("success"):
                raise RuntimeError(f"statistics call unsuccessful for {name} {ptype}")
            d = st["data"]
            month = (p.get("startDate") or "")[:7]
            fn = f"{s.get('division_id', 'x')}_{sid}_{month or 'na'}.json"
            with open(os.path.join(RAW, fn), "w") as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
            row = dict(
                unit=name, month=month,
                collected_at=d.get("dataCollectedAt"),
                personnel_killed=d.get("personnel", {}).get("killed"),
                personnel_wounded=d.get("personnel", {}).get("wounded"),
                strike_missions=d.get("flights", {}).get("strike"),
                recon_missions=d.get("flights", {}).get("recon"),
                total_hit=d.get("totalTargetsHit"),
                total_destroyed=d.get("totalTargetsDestroyed"),
            )
            for t in d.get("targetsByType", []):
                tc = t.get("targetClassId")
                max_tc = max(max_tc, tc)
                row[f"tc{tc:02d}_hit"] = t.get("hit")
                row[f"tc{tc:02d}_destroyed"] = t.get("destroyed")
            rows.append(row)
            print(f"  {name} | {month} | hit={row['total_hit']}")

    if not rows:
        raise RuntimeError("no monthly rows collected")
    if max_tc > N_TC:
        print(f"NOTE: new target class tc{max_tc:02d} observed (> tc{N_TC}) — "
              f"add it to data/target_classes.csv", file=sys.stderr)

    fixed = ["unit", "month", "collected_at", "personnel_killed", "personnel_wounded",
             "strike_missions", "recon_missions", "total_hit", "total_destroyed"]
    tcs = [f"tc{i:02d}_{k}" for i in range(1, max(N_TC, max_tc) + 1)
           for k in ("hit", "destroyed")]
    out = os.path.join(DATA, "killboard_monthly.csv")
    rows.sort(key=lambda r: (r["month"], r["unit"]))
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fixed + tcs, restval=0)
        w.writeheader()
        w.writerows(rows)
    print(f"\n{len(rows)} unit-months -> {out}")


if __name__ == "__main__":
    main()
