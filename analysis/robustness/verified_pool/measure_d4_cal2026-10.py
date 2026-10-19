#!/usr/bin/env python3
"""measure_d4_cal2026-10.py — the D4 check on the October caliber (REPO-AUTHORED, 2026-09-23; new file,
nothing existing edited).

D4 (the author's design record of 2026-09-22, private archive): the network-route incumbents who are not on the verified
economics roster are removed at FRAME-BUILD time, because the October network pool IS the verified
roster (D2). build_verified_pool.py, written for the 2026-08-28 canon, still reads the 2026-08-09
roster (data/raw_verified/roster_econ_verified.parquet, 920 author_ids); the October frames were built
from data/cal2026-10/roster_econ_verified_2026-10.parquet (920 + 88 D3 additions = 1,008). This script
applies the builder's OWN identity rule (a frame person is on a roster if its id matches a roster
author_id either directly as P_<author_id> or through the 2026-07-16 11-school person map) to both
rosters and records, per frame:
  - how many persons the builder's rule would drop against the 08-09 roster, split by route, and how
    many of those are the October D3 additions (data/cal2026-10/roster_added_2026-10.csv);
  - how many persons are not on the October roster (the D4 measurement proper; expected 0 = the
    builder would drop 0 persons and the filtered frame is the unfiltered frame).
Reads nothing it does not hash. Writes <outdir>/d4_measure_report.json.
Run: SAR_ROBUST_OUTDIR=data/cal2026-10/robustness/verified_pool setup/.venv/bin/python \
       analysis/robustness/verified_pool/measure_d4_cal2026-10.py
"""
import hashlib, json, os, pathlib, sys

import duckdb

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths

P = load_paths()
OUT = REPO / os.environ.get("SAR_ROBUST_OUTDIR", "data/cal2026-10/robustness/verified_pool")
F1 = REPO / "data/frames/p1_frame_econ.csv"
F2 = REPO / "data/frames/p2_becoming_econ.csv"
OLD = REPO / "data/raw_verified/roster_econ_verified.parquet"
NEW = REPO / "data/cal2026-10/roster_econ_verified_2026-10.parquet"
ADD = REPO / "data/cal2026-10/roster_added_2026-10.csv"
PM = pathlib.Path(P["ssd_root"]) / "derived/u2_person_map_11school_2026-07-16/person_map/data.parquet"


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


for p in [F1, F2, OLD, NEW, ADD, PM]:
    assert pathlib.Path(p).is_file(), f"missing input {p}"

con = duckdb.connect()
con.execute(f"create table pm as select author_id, person_id from '{PM}'")
con.execute(f"create table f1 as select incumbent_person_id pid, event_id, channel from read_csv_auto('{F1}')")
con.execute(f"create table f2 as select 'P_'||pid pid, event_id, channel from read_csv_auto('{F2}')")
q = lambda s: con.execute(s).fetchone()[0]


def roster_pids(name, src, reader):
    con.execute(f"create table {name} as select distinct 'P_'||v.author_id pid from {reader} v "
                f"union select distinct pm.person_id pid from {reader} v join pm using(author_id)")
    return {"file": str(src.relative_to(REPO)), "author_ids": q(f"select count(distinct author_id) from {reader}"),
            "person_ids_both_forms": q(f"select count(*) from {name}")}


rosters = {"roster_2026-08-09": roster_pids("old_p", OLD, f"'{OLD}'"),
           "roster_2026-10": roster_pids("new_p", NEW, f"'{NEW}'"),
           "additions_2026-10": roster_pids("add_p", ADD, f"read_csv_auto('{ADD}')")}


def measure(t):
    d = {"persons": q(f"select count(distinct pid) from {t}"),
         "persons_by_channel": dict(con.execute(f"select channel, count(distinct pid) from {t} group by 1 order by 1").fetchall()),
         "events": q(f"select count(distinct event_id) from {t}"),
         "rows": q(f"select count(*) from {t}")}
    for lab, r in (("vs_roster_2026-08-09", "old_p"), ("vs_roster_2026-10", "new_p")):
        nv = f"pid not in (select pid from {r})"
        d[lab] = {
            "persons_not_on_roster": q(f"select count(distinct pid) from {t} where {nv}"),
            "roster_route_persons_not_on_roster": q(f"select count(distinct pid) from {t} where channel in ('dept_only','both') and {nv}"),
            "network_only_persons_not_on_roster": q(f"select count(distinct pid) from {t} where {nv} and pid not in (select pid from {t} where channel <> 'network')"),
            "rows_of_persons_not_on_roster": q(f"select count(*) from {t} where {nv}"),
            "not_on_roster_but_in_2026-10_additions": q(f"select count(distinct pid) from {t} where {nv} and pid in (select pid from add_p)"),
        }
    d["additions_2026-10_present"] = q(f"select count(distinct pid) from {t} where pid in (select pid from add_p)")
    return d


rep = {
    "generated": "2026-09-23",
    "purpose": "D4 check on the October caliber: would build_verified_pool.py's rule drop anyone from the October frames?",
    "identity_rule": "frame person id == 'P_'||author_id, or == person_id of that author_id in the 2026-07-16 11-school person map (build_verified_pool.py's rule, unchanged)",
    "rosters": rosters,
    "panel1": measure("f1"),
    "panel2": measure("f2"),
    "inputs_sha256": {str(p.relative_to(REPO)) if str(p).startswith(str(REPO)) else str(p): sha(p) for p in [F1, F2, OLD, NEW, ADD, PM]},
}
p1, p2 = rep["panel1"]["vs_roster_2026-10"], rep["panel2"]["vs_roster_2026-10"]
rep["d4_verdict"] = ("PASS: 0 persons off the October roster in both frames — the builder would drop 0 persons; "
                     "the filtered frames are the unfiltered frames"
                     if p1["persons_not_on_roster"] == 0 and p2["persons_not_on_roster"] == 0
                     else f"FAIL: {p1['persons_not_on_roster']} (P1) / {p2['persons_not_on_roster']} (P2) persons off the October roster")
OUT.mkdir(parents=True, exist_ok=True)
(OUT / "d4_measure_report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
print(json.dumps({k: rep[k] for k in ("rosters", "panel1", "panel2", "d4_verdict")}, indent=1))
