import csv
# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "stars").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout,
                                staged_run_dir as _sar_staged)
cand={r['author_id']:r for r in csv.DictReader(open('data/fnfix_candidates_restake.csv')) if r['field']=='econ'}
rs={r['author_id']:r for r in csv.DictReader(open('data/fnfix_restake_2026-08-15.csv'))}
rc={}
for f in ('data/poach_fn_recheck_econ_2026-08-15.csv','data/poach_fn_recheck_econ_U4flagged9_2026-08-16.csv'):
    for r in csv.DictReader(open(f)): rc[r['author_id']]=r
SCHOOL_INST={"adelaide":"I5681781","anu":"I118347636","deakin":"I149704539","macquarie":"I99043593","melbourne":"I165779595","monash":"I56590836","sydney":"I129604602","unsw":"I31746571","uq":"I165143802","uts":"I114017466","uwa":"I177877127"}
rows=[]; dropped=[]
for aid,c in cand.items():
    r=rs[aid]
    if r['after_pass']!='True': dropped.append((c['name'],r['after_pct'])); continue
    rows.append({"author_id":aid,"name":c['name'],"school":c['school'],"arrival":c['arrival_true'],"dept_id":SCHOOL_INST[c['school']],
                 "evidence_url":rc[aid]['evidence_urls'].split(';')[0],"verdict_source":"human_web_verified_round2_2026-08-15"})
E=str(_sar_staged(_sar_legacy_thesis() / "v2_output/econ_fnfix_2026-08-15"))
with open(f"{E}/data/new_events_econ.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("econ new events", len(rows), "dropped", dropped)
from collections import Counter; print(Counter(r['school'] for r in rows))
