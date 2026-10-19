#!/usr/bin/env python3
"""00_make_u4_aug.py — economics "overseas-poach gate false negative" fix: build the incremental inputs for prodlib u4_frozen

Cause: OpenAlex backfills a scholar's later addresses onto early works → U4 is_foreign_poach wrongly
returns False → a real overseas poach is dropped (gold case: A5086383420, Monash 2019, pct .9986).
The missed stars confirmed by manual verification are in
data/new_events_econ.csv (columns: author_id,name,school,arrival,dept_id,evidence_url,verdict_source).

Output (new events only; the old 79 stay untouched — old network-frame rows are kept verbatim downstream):
  u4_aug/events/data.parquet     same U4 events schema
  u4_aug/star_set/star_set.parquet  full U4 star_set table, with is_foreign_poach flipped to True for the new stars (fail-loud: not in the table / flag not set)
  config/econ_fnfix.json         = econ_p10.json with events/star_set/run_dir swapped, coupling→na, no golden
"""
import csv, json, os, sys
import pyarrow as pa, pyarrow.parquet as pq

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
                                deferred_output_target as _sar_lazyout)
ROOT = str(_sar_rd(_sar_legacy_thesis()))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
U4 = str(_sar_rd(_sar_derived_root() / "u4_star_set_p10_80ev_2026-07-22"))
NEW = f"{BASE}/data/new_events_econ.csv"
SCHOOL_INST = {"adelaide": "I5681781", "anu": "I118347636", "deakin": "I149704539",
               "macquarie": "I99043593", "melbourne": "I165779595", "monash": "I56590836",
               "sydney": "I129604602", "unsw": "I31746571", "uq": "I165143802",
               "uts": "I114017466", "uwa": "I177877127"}

new = list(csv.DictReader(open(NEW)))
assert new, "new_events_econ.csv is empty"
RESTAKE = {r["author_id"]: r for r in csv.DictReader(open(
    f"{ROOT}/v2_output/multidisc_gold_2026-08-10/data/fnfix_restake_2026-08-15.csv"))}
for r in new:
    assert r["author_id"] in RESTAKE and RESTAKE[r["author_id"]]["after_pass"] == "True", f"{r['author_id']} did not pass the recomputed threshold"
synthesized, relit = [], []
ev_old = pq.read_table(f"{U4}/events/data.parquet")
ss = pq.read_table(f"{U4}/star_set/star_set.parquet").to_pylist()
by_a = {s["author_id"]: s for s in ss}
old_ids = set(ev_old.column("star_person_id").to_pylist())

rows = []
for r in new:
    a = r["author_id"]; arr = int(r["arrival"])
    s = by_a.get(a)
    if a in old_ids:
        sys.exit(f"FAIL: {a} is already among the 79 events")
    # U4's frozen star_set holds only people in U4's candidate pool at the time; of the missed stars, 20 are not in the table and 10 are in the table but their flag is not set
    # (U4's p10 batch is not exhaustive). Here star_set rows are synthesised/flipped with the fnfix recomputed threshold (data/fnfix_restake, same rules: stock at t−1, 2002 × academic-age cell,
    # naive rank, top 10%, cell_n>=30, academic age>=2); percentile/cell_n come from the recomputation (never left empty).
    rk = RESTAKE[a]
    if s is None:
        s = {"author_id": a, "name": r["name"], "dept": f"{r['school']}_econ", "arrival": arr,
             "subfield": "2002", "age_bin": rk["after_cell"].split("|")[1], "academic_age": float(rk["aage"]),
             "stock": float(rk["after_stock"]), "percentile": float(rk["after_pct"]), "cell_n": float(rk["after_cell_n"]),
             "is_star_1pct": True, "is_star_5pct": float(rk["after_pct"]) >= 0.95, "age_eligible": True,
             "is_foreign_poach": True}
        by_a[a] = s; synthesized.append(a)
    else:
        if s.get("is_star_1pct") is not True: relit.append(a)
        s["is_star_1pct"] = True; s["age_eligible"] = True
        s["arrival"] = arr; s["stock"] = float(rk["after_stock"]); s["percentile"] = float(rk["after_pct"])
        s["cell_n"] = float(rk["after_cell_n"]); s["academic_age"] = float(rk["aage"]); s["age_bin"] = rk["after_cell"].split("|")[1]
    if s["dept"] != f"{r['school']}_econ":
        print(f"  ⚠ {a} star_set dept={s['dept']} vs manual-check school={r['school']} (manual check takes precedence; logged)"); s["dept"] = f"{r['school']}_econ"
    rows.append({"event_id": f"{a}:{arr}", "dept_id": r.get("dept_id") or SCHOOL_INST[r["school"]],
                 "star_person_id": a, "arrival_year": arr, "t_minus_1": arr - 1,
                 "arrival_source": r.get("verdict_source") or "human_web_verified_2026-08-15",
                 "arrival_evidence_strength": "strong", "modal_inst_year": None,
                 "prior_main_exited": None, "min_tenure_ok": None, "departed_year": None})
    by_a[a]["is_foreign_poach"] = True

os.makedirs(f"{BASE}/u4_aug/events", exist_ok=True); os.makedirs(f"{BASE}/u4_aug/star_set", exist_ok=True)
pq.write_table(pa.Table.from_pylist(rows, schema=ev_old.schema), f"{BASE}/u4_aug/events/data.parquet")
pq.write_table(pa.Table.from_pylist(list(by_a.values()),
                                    schema=pq.read_table(f"{U4}/star_set/star_set.parquet").schema),
               f"{BASE}/u4_aug/star_set/star_set.parquet")

cfg = json.load(open(f"{ROOT}/v2_output/multidisc_prod_2026-07-24/config/econ_p10.json"))
cfg["label"] = f"econ 海外挖角门假阴性补漏 {len(rows)} 起（只含新事件；老 79 起网络帧行下游逐字保留）"
cfg["events"] = {"mode": "u4_frozen", "events_dir": f"{BASE}/u4_aug/events",
                 "star_set_dir": f"{BASE}/u4_aug/star_set"}
cfg["dose_coupling_join"] = {"mode": "na"}
cfg["supplement_jsonl"] = f"{BASE}/data/edges_supplement_fnfix.jsonl"   # star-side supplement edges (must be fetched first; 01_merge fetches them)
cfg["run_dir"] = f"{BASE}/runs/econ_fnfix"
cfg.pop("golden", None)
os.makedirs(f"{BASE}/config", exist_ok=True)
json.dump(cfg, open(f"{BASE}/config/econ_fnfix.json", "w"), ensure_ascii=False, indent=2)
print(f"OK: {len(rows)} new events → u4_aug/ + config/econ_fnfix.json; star_set {len(synthesized)} rows synthesized / {len(relit)} rows flagged")
for r in rows: print("  ", r["event_id"], r["dept_id"])
