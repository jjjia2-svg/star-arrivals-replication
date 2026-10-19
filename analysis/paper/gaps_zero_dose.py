#!/usr/bin/env python3
"""gaps_zero_dose.py — §3 exact-zero dose shares (sec3_strategy.tex).

The thesis: incumbents whose dose is exactly zero "16 percent of relations in
economics, 9 in chemistry, 32 in mathematics" are the untreated comparison.

Computed here per discipline from the P1 frames at the SAME unit as
ledger_main.py's {d}_dose_bins_pct: one row per incumbent-event relation
(DISTINCT incumbent_person_id, event_id, dose_topic; dose is frozen, so the
triple is the relation), denominator = relations with a non-NULL dose — but
counting dose_topic == 0 exactly, not the [0, 0.1) bin.

Reads:   data/frames/p1_frame_{econ,chemistry,math_stats}.csv
Writes:  output/paper/gaps_zero_dose.json  ({d}_zero_dose_share_pct, 1 dp)

Asserts each share rounds to the thesis integer; a mismatch exits non-zero —
it is reported, never tuned away.

Written 2026-08-24 for the star_arrivals_replication repo (M2/T4).
Freeze-wave Task 8 (2026-08-28): on the promoted caliber frames the measured shares are
15.4 / 10.3 / 33.1 percent, and the thesis §3 sentence was updated 16/9/32 -> 15/10/33 in the
same wave (each edit \REV-marked). The caliber-rebuild ledger's provisional note "15/10/32"
under-rounded the mathematics share (33.1 rounds to 33, not 32); the measured value governs.
cal2026-10 (2026-09-23, the October caliber is the canon): on the October frames the measured
shares are 8.2 / 5.8 / 30.6 percent (548/6,643, 160/2,780, 530/1,730 relations): the October
network channel keeps only verified-roster members in post at arrival, and the relations it drops
were disproportionately zero-dose. THESIS is the October canon (the thesis prints 8/6/31 once the
cal2026-10 repin lands); PRE_OCT_THESIS (15/10/33) is what the 2026-08-28 thesis printed. Both go
into the JSON.
final review #5 (the gaps_zenou N11 pattern): the THESIS assertion holds in the October canon only.
In M (analysis.lib.canon.mode() == 'M') the shares are reported next to the October values
(`_october`, `_diff_vs_october`, underscore metadata) with a CHANGED line per moved share and exit 0;
the sentinel D pins and replace.py repin the sec3 sentence. An M frame with no relation carrying a
non-NULL dose is 'MISSING INPUT', exit 1, before anything is written. October keeps every byte,
line and exit code.
Run:  python3 analysis/paper/gaps_zero_dose.py
"""
import json, sys
from pathlib import Path
import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths
from analysis.lib import canon

P = load_paths()
MODE = canon.mode()     # 'october' or 'M'; a mixed or malformed config is a CanonError
FR = {"econ": str(P["frames"] / "p1_frame_econ.csv"),
      "chem": str(P["frames"] / "p1_frame_chemistry.csv"),
      "math": str(P["frames"] / "p1_frame_math_stats.csv")}
THESIS = {"econ": 8, "chem": 6, "math": 31}           # October canon (cal2026-10)
PRE_OCT_THESIS = {"econ": 15, "chem": 10, "math": 33}  # the 2026-08-28 thesis
OUT_JSON = P["output"] / "paper" / "gaps_zero_dose.json"

con = duckdb.connect(); con.execute("PRAGMA threads=8")
N, mismatches = {"_provenance": {}}, []
for d, fp in FR.items():
    zero, tot = con.execute(f"""SELECT sum(CASE WHEN dose_topic=0 THEN 1 ELSE 0 END), count(*)
        FROM (SELECT DISTINCT incumbent_person_id, event_id, dose_topic
              FROM read_csv_auto('{fp}') WHERE dose_topic IS NOT NULL)""").fetchone()
    if MODE == "M" and (not tot or zero is None):
        print(f"MISSING INPUT {d}: no relation with a non-NULL dose_topic in {canon.key(fp)}", file=sys.stderr)
        sys.exit(1)
    share = round(100 * zero / tot, 1)
    N[f"{d}_zero_dose_share_pct"] = share
    N["_provenance"][f"{d}_zero_dose_share_pct"] = f"{fp} ({zero} of {tot} relations with dose_topic == 0)"
    print(f"{d}: {zero}/{tot} = {share}% (thesis prints {THESIS[d]})")
    if round(share) != THESIS[d]:
        mismatches.append((d, share, THESIS[d]))

N["_pre_october_thesis_pct"] = PRE_OCT_THESIS
if MODE == "M":
    # final review #5: an M run reports each share next to its October value instead of failing on it;
    # the sentinel repin and tools/r1_number_diff.py read the new values (underscore keys are metadata)
    N["_october"] = dict(THESIS)
    N["_diff_vs_october"] = {f"{d}_zero_dose_share_pct": {"october": THESIS[d], "new": N[f"{d}_zero_dose_share_pct"],
                                                           "changed": round(N[f"{d}_zero_dose_share_pct"]) != THESIS[d]}
                             for d in FR}
    mismatches = []
OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
json.dump(N, open(OUT_JSON, "w"), ensure_ascii=False, indent=1)
print("wrote", OUT_JSON)
if MODE == "M":
    for k, v in N["_diff_vs_october"].items():
        if v["changed"]:
            print(f"CHANGED {k}: october {v['october']} -> new {v['new']}")
if mismatches:
    for d, share, want in mismatches:
        print(f"MISMATCH {d}: derived {share}% does not round to the thesis's {want}", file=sys.stderr)
    sys.exit(1)
