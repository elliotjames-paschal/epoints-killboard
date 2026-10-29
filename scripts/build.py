#!/usr/bin/env python3
"""Validate the dataset and stamp site metadata. Exits non-zero on any violation,
so the weekly workflow fails instead of publishing bad data.

Rules enforced:
  - every row of prices.csv and events.csv has a non-empty http(s) source
  - every prices.csv category_id exists in categories.csv
  - categories.csv killboard_fields reference real killboard columns
  - dates parse; valid_from < valid_to; no overlapping validity intervals
    for the same (category, basis)
  - killboard_monthly.csv exists, is non-trivial, and covers every month
    from its first month to its last (no silent gaps)

Writes data/meta.json with row counts and last-updated stamps for the site footer.
"""
import csv
import datetime
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
errors = []


def err(msg):
    errors.append(msg)


def read(name):
    with open(os.path.join(DATA, name), newline="") as f:
        return list(csv.DictReader(f))


def parse_date(s):
    """Accept YYYY, YYYY-MM, YYYY-MM-DD; return a sortable date (first day of period)."""
    s = (s or "").strip()
    for fmt, pad in (("%Y-%m-%d", s), ("%Y-%m", s + "-01"), ("%Y", s + "-01-01")):
        try:
            return datetime.datetime.strptime(pad, "%Y-%m-%d").date()
        except ValueError:
            continue
    return None


def main():
    cats = read("categories.csv")
    prices = read("prices.csv")
    events = read("events.csv")
    tcs = read("target_classes.csv")

    cat_ids = {c["category_id"] for c in cats}
    kb_fixed = {"personnel_killed", "personnel_wounded", "strike_missions",
                "recon_missions", "total_hit", "total_destroyed"}
    kb_cols = kb_fixed | {f"{t['tc_id']}_{k}" for t in tcs for k in ("hit", "destroyed")}

    for i, r in enumerate(prices, 2):
        if not re.match(r"^https?://", r.get("source", "")):
            err(f"prices.csv:{i}: missing/invalid source URL")
        if r["category_id"] not in cat_ids:
            err(f"prices.csv:{i}: unknown category_id {r['category_id']!r}")
        if not (r.get("points") or r.get("points_max")):
            err(f"prices.csv:{i}: neither points nor points_max set")
        if parse_date(r["valid_from"]) is None:
            err(f"prices.csv:{i}: bad valid_from {r['valid_from']!r}")
        if r.get("valid_to") and parse_date(r["valid_to"]) is None:
            err(f"prices.csv:{i}: bad valid_to {r['valid_to']!r}")

    spans = {}
    for i, r in enumerate(prices, 2):
        f, t = parse_date(r["valid_from"]), parse_date(r.get("valid_to"))
        if f and t and f >= t:
            err(f"prices.csv:{i}: valid_from >= valid_to")
        spans.setdefault((r["category_id"], r["basis"]), []).append((f, t, i))
    for (cat, basis), ivs in spans.items():
        ivs.sort(key=lambda x: x[0] or datetime.date.min)
        for (f1, t1, i1), (f2, t2, i2) in zip(ivs, ivs[1:]):
            if t1 is None or (f2 and t1 and f2 < t1):
                err(f"prices.csv:{i1}&{i2}: overlapping/unclosed intervals for {cat}/{basis}")

    for i, r in enumerate(events, 2):
        if not re.match(r"^https?://", r.get("source", "")):
            err(f"events.csv:{i}: missing/invalid source URL")
        if parse_date(r["date"].split("..")[0].replace("bracket ", "")) is None and \
           r.get("precision") != "bracket":
            err(f"events.csv:{i}: bad date {r['date']!r}")

    for i, c in enumerate(cats, 2):
        for fld in filter(None, (c.get("killboard_fields") or "").split(";")):
            if fld not in kb_cols:
                err(f"categories.csv:{i}: unknown killboard field {fld!r}")
        if c["on_killboard"] not in ("yes", "partial", "no"):
            err(f"categories.csv:{i}: on_killboard must be yes/partial/no")
        if c["on_killboard"] != "no" and not c.get("killboard_fields"):
            err(f"categories.csv:{i}: on_killboard={c['on_killboard']} but no killboard_fields")

    kb_path = os.path.join(DATA, "killboard_monthly.csv")
    kb_meta = {}
    if os.path.exists(kb_path):
        kb = read("killboard_monthly.csv")
        months = sorted({r["month"] for r in kb if r["month"]})
        if len(kb) < 50:
            err(f"killboard_monthly.csv: only {len(kb)} rows — collection looks broken")
        if months:
            cur, last = months[0], months[-1]
            seq = []
            y, m = map(int, cur.split("-"))
            while f"{y:04d}-{m:02d}" <= last:
                seq.append(f"{y:04d}-{m:02d}")
                m += 1
                if m == 13:
                    y, m = y + 1, 1
            missing = [mo for mo in seq if mo not in months]
            if missing:
                err(f"killboard_monthly.csv: month gaps {missing}")
        kb_meta = {"rows": len(kb), "units": len({r['unit'] for r in kb}),
                   "months": f"{months[0]}..{months[-1]}" if months else "",
                   "collected_at": max((r.get("collected_at") or "") for r in kb)}
    else:
        err("killboard_monthly.csv missing — run scripts/kb_collect.py first")

    if errors:
        print("VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        sys.exit(1)

    meta = {
        "built_at": datetime.datetime.now(datetime.timezone.utc)
                    .strftime("%Y-%m-%d %H:%M UTC"),
        "killboard": kb_meta,
        "counts": {"categories": len(cats), "price_rows": len(prices),
                   "events": len(events), "target_classes": len(tcs)},
    }
    with open(os.path.join(DATA, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print(f"OK — {meta['counts']} | killboard {kb_meta.get('months', 'n/a')}")


if __name__ == "__main__":
    main()
