# E-Points & the Killboard

A maintained dataset of Ukraine's marketplace for verified military output: e-points
bounty prices by category over time, category introductions and repricings, and
unit-month verified output from the Unmanned Systems Forces killboard
([sbs-group.army](https://sbs-group.army)). Updated weekly.

**Site:** the dashboard renders this repository directly via GitHub Pages —
timeline of every pricing event (each with a source), price intervals by category,
and the killboard panel. See the glossary page for definitions and caveats.

## Data

| File | Contents |
|---|---|
| `data/panel.csv` | **The merged analysis panel** (generated): unit × month × category — killboard output next to the price in force that month; blank output = unobservable on the killboard, blank points = unpriced or value unpublished |
| `data/prices.csv` | Point values as validity intervals: category × basis × (from, to), confidence, source URL per row |
| `data/events.csv` | Timeline: launches, repricings, category expansions, platform events, proposals — source per row |
| `data/categories.csv` | Priced-category registry with killboard-observability flag (`yes`/`partial`/`no`) |
| `data/killboard_monthly.csv` | One row per USF unit per month: casualties, missions, totals, 43 target classes (hit/destroyed) |
| `data/killboard_reconstructed.csv` | Jun 11 – Sep 30 2025 per-unit block, reconstructed (method documented per row) |
| `data/killboard_prehistory.csv` | Pre-killboard monthly series (Dec 2024 – Aug 2025) from USF commander Brovdi's public Telegram reports: force-wide verified personnel hits, 414th-brigade series, USF-grouping summer totals |
| `data/target_classes.csv` | Killboard target-class key: Ukrainian original, English translation, analytic group |

Design rule: **no source, no row.** `scripts/build.py` fails the build if any price
or event lacks a source URL, if validity intervals overlap, or if the killboard
panel develops month gaps.

## Pipeline

A GitHub Action (`.github/workflows/weekly.yml`) runs every Monday: pulls the
killboard's public API (`scripts/kb_collect.py`, stdlib only), revalidates all
tables, and commits. Git history preserves every weekly snapshot. The curated
tables (`prices`, `events`, `categories`) are hand-maintained — new repricings are
added by hand with sources, never scraped.

Local fallback if GitHub runner IPs are ever blocked by the API: run
`python3 scripts/kb_collect.py && python3 scripts/build.py` locally and push
(a `launchd`/cron job does this fine).

## Sources & citation

Killboard data comes from [«Підрахуйка» (sbs-group.army)](https://sbs-group.army/en/),
the official public killboard of Ukraine's Unmanned Systems Forces, via its public
API; raw JSON snapshots are preserved under `data/raw/` and in git history. Price
and event data are compiled from official announcements (MOD, Mintsifra/Fedorov,
Brave1) and reliable press — every row carries its source URL.

If you use this data, please cite the repository and credit the killboard as the
underlying output source. Collaboration welcome: **paschal@stanford.edu**.
