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

Also generates data/panel.csv — the merged analysis panel: one row per
unit x month x priced category, killboard output next to the price in force
that month. Output is blank where the killboard cannot observe the category
(on_killboard = no); points are blank where no value was ever published or the
category was not yet priced. Derived file: never edit by hand.

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
        if not re.match(r"^https?://", c.get("source", "")):
            err(f"categories.csv:{i}: missing/invalid source URL")
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

    # ---- the merged panel: unit x month x category, output + price in force ----
    def output_fields(c):
        """(primary_fields, damaged_fields) for a category. Named counters
        (personnel_killed, recon_missions, ...) win over tc columns; otherwise
        tc *_destroyed are primary and tc *_hit are the damaged measure."""
        flds = [f for f in (c.get("killboard_fields") or "").split(";") if f]
        counters = [f for f in flds if not f.startswith("tc")]
        if counters:
            return counters, []
        return ([f for f in flds if f.endswith("_destroyed")],
                [f for f in flds if f.endswith("_hit")])

    def price_in(rows_, month):
        """The price row whose validity interval contains the 1st of `month`."""
        d = parse_date(month)
        for r in rows_:
            f, t = parse_date(r["valid_from"]), parse_date(r.get("valid_to"))
            if f and f <= d and (t is None or d < t):
                return r
        return None

    # a category can have several live bases (operator: 25 per kill AND 15 per
    # wounded); the panel's `points` column reports the highest-priority one and
    # names it in `points_basis` — the full set stays in prices.csv
    BASIS_PRIORITY = ["per_kill", "per_destroyed", "per_capture",
                      "per_mission", "per_event", "per_wounded"]
    price_rows = {}
    for r in prices:
        kind = "damaged" if r["basis"] == "per_hit" else "primary"
        price_rows.setdefault((r["category_id"], kind), []).append(r)

    def primary_price(cat, month):
        rows_ = price_rows.get((cat, "primary"), [])
        for basis in BASIS_PRIORITY:
            hit = price_in([r for r in rows_ if r["basis"] == basis], month)
            if hit:
                return hit
        return None

    panel = []
    for row in kb:
        if not row["month"]:
            continue
        for c in cats:
            prim, dam = output_fields(c)
            def total(fields):
                if not fields or c["on_killboard"] == "no":
                    return ""
                return sum(int(row.get(f) or 0) for f in fields)
            pp = primary_price(c["category_id"], row["month"])
            pd = price_in(price_rows.get((c["category_id"], "damaged"), []), row["month"])
            panel.append({
                "unit": row["unit"], "month": row["month"],
                "category_id": c["category_id"], "on_killboard": c["on_killboard"],
                "output": total(prim), "output_damaged": total(dam),
                "points": (pp or {}).get("points", ""),
                "points_max": (pp or {}).get("points_max", ""),
                "points_basis": (pp or {}).get("basis", ""),
                "points_damaged": (pd or {}).get("points", ""),
                "price_confidence": (pp or {}).get("confidence", ""),
            })
    panel.sort(key=lambda r: (r["month"], r["unit"], r["category_id"]))
    with open(os.path.join(DATA, "panel.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(panel[0].keys()))
        w.writeheader()
        w.writerows(panel)
    print(f"panel.csv: {len(panel)} rows "
          f"({kb_meta['rows']} unit-months x {len(cats)} categories)")

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
