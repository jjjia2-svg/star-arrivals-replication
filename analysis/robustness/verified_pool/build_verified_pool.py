#!/usr/bin/env python3
"""build_verified_pool.py — economics incumbents who enter only through the star's network but are
not on the verified economics roster; filtered Panel 1 and Panel 2 frames without them.

REPO-AUTHORED, 2026-09-13. Why: the exposure population has two routes. The roster route was
switched to the hand-verified economics roster of 2026-08-09 (920 author_ids). The network route
still intersects the star's two-hop network with the OLD, unverified 11-department pool (registry
v5 + proj8 + Adelaide merged, 1,165 author_ids). Some network-route incumbents are therefore people
the verification rejected (wrong department or wrong OpenAlex identity) or people removed by the
2026-07-20 roster cleaning. Measured on 2026-09-13: every verified person is in the old pool, so
the fix is one-directional: drop the network-route incumbents who are not on the verified roster.

Identity is compared at the person level, in both forms a person id takes in this package: the
current frames write a verified roster member as P_<author_id>, while the old pool was built with the
2026-07-16 11-school person map, which merges some author_ids into another person id. A frame person
counts as verified if its id matches a verified author_id in EITHER form (measured 2026-09-13: 36
verified roster-route persons match only directly, and 43 network-route persons only through the map). Gates, each an assert:
  - every roster-route incumbent (channel dept_only or both) in both frames is on the verified roster
    (positive control: the identity mapping works);
  - every excluded incumbent is network-route only;
  - every excluded incumbent is in the old pool (the network route could only have admitted pool members);
  - the filtered frames are the original frames minus exactly the excluded persons' lines, byte for
    byte on every kept line.

Inputs (sha256 recorded in the build report):
  data/frames/p1_frame_econ.csv, data/frames/p2_becoming_econ.csv
  data/raw_verified/roster_econ_verified.parquet
  <ssd_root>/derived/u2_person_map_11school_2026-07-16/person_map/data.parquet
  <ssd_root>/derived/u0p5_roster/{registry_v5_2026-07-20, adelaide_backfill_2007_2021_2026-07-20}/*.parquet,
  <ssd_root>/derived/u5u6_final_2026-07-18_work/roster_v4_proj8/*.parquet        (old pool; classification)
  <legacy>/v2_output/econ_roster_verify_2026-08-09/rejected_persons.csv            (reasons; classification)
  <legacy>/v2_output/explore_within_dept_2026-07-20/data/roster_clean_11school.parquet (994; classification)
Writes data/robustness_2026-09-13_verified_pool/{frames/, excluded_persons.csv, build_report.json}.
Run:  setup/.venv/bin/python analysis/robustness/verified_pool/build_verified_pool.py
"""
import csv, glob, hashlib, json, os, pathlib, sys

import duckdb

REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths

P = load_paths()
DERIVED = pathlib.Path(P["ssd_root"]) / "derived"
LEGACY = pathlib.Path(P["legacy_thesis"]) / "v2_output"
OUT = REPO / os.environ.get("SAR_ROBUST_OUTDIR", "data/robustness_2026-09-13_verified_pool")   # env override (2026-09-23); old value = default

F1 = REPO / "data/frames/p1_frame_econ.csv"
F2 = REPO / "data/frames/p2_becoming_econ.csv"
VER = REPO / "data/raw_verified/roster_econ_verified.parquet"
PM = DERIVED / "u2_person_map_11school_2026-07-16/person_map/data.parquet"
POOL = (sorted(glob.glob(str(DERIVED / "u0p5_roster/registry_v5_2026-07-20/dept_roster_panel_*.parquet")))
        + sorted(glob.glob(str(DERIVED / "u5u6_final_2026-07-18_work/roster_v4_proj8/dept_roster_panel_*.parquet")))
        + sorted(glob.glob(str(DERIVED / "u0p5_roster/adelaide_backfill_2007_2021_2026-07-20/*.parquet"))))
REJ = LEGACY / "econ_roster_verify_2026-08-09/rejected_persons.csv"
R994 = LEGACY / "explore_within_dept_2026-07-20/data/roster_clean_11school.parquet"


def sha(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


for p in [F1, F2, VER, PM, REJ, R994]:
    assert pathlib.Path(p).is_file(), f"missing input {p}"
assert len(POOL) == 13, f"expected 13 old-pool roster files, found {len(POOL)}"

con = duckdb.connect()
con.execute(f"create table pm as select author_id, person_id from '{PM}'")
con.execute("create table ver_p as "
            f"select distinct 'P_'||v.author_id pid from '{VER}' v "
            f"union select distinct pm.person_id pid from '{VER}' v join pm using(author_id)")
plist = ",".join(f"'{p}'" for p in POOL)
con.execute(f"create table pool_raw as select * from read_parquet([{plist}], union_by_name=true)")
con.execute("create table pool_p as select distinct coalesce(pm.person_id, 'P_'||x.author_id) pid, "
            "first(x.display_name) AS dname from pool_raw x left join pm using(author_id) group by 1")
con.execute(f"create table r994_p as select distinct coalesce(pm.person_id, 'P_'||x.author_id) pid "
            f"from '{R994}' x left join pm using(author_id)")
con.execute(f"create table rej_p as select coalesce(pm.person_id, 'P_'||r.author_id) pid, "
            f"first(r.display_name) AS dname, first(r.reject_cause) AS rcause "
            f"from read_csv_auto('{REJ}') r left join pm using(author_id) group by 1")
# frames: Panel 1 carries person ids with the P_ prefix, Panel 2 without it
con.execute(f"create table f1 as select incumbent_person_id pid, event_id, channel from read_csv_auto('{F1}')")
con.execute(f"create table f2 as select 'P_'||pid pid, event_id, channel from read_csv_auto('{F2}')")

# gate 1: positive control — the roster route is entirely on the verified roster
for t in ("f1", "f2"):
    bad = con.execute(f"select count(distinct pid) from {t} where channel in ('dept_only','both') "
                      "and pid not in (select pid from ver_p)").fetchone()[0]
    assert bad == 0, f"{t}: {bad} roster-route persons not on the verified roster — identity mapping broken"

con.execute("create table excl as select distinct pid from (select pid from f1 union select pid from f2) "
            "where pid not in (select pid from ver_p)")
# gate 2: excluded persons enter only through the network route
for t in ("f1", "f2"):
    bad = con.execute(f"select count(distinct pid) from {t} where pid in (select pid from excl) "
                      "and channel <> 'network'").fetchone()[0]
    assert bad == 0, f"{t}: an excluded person has a roster-route row"
# gate 3: excluded persons are all in the old pool
bad = con.execute("select count(*) from excl where pid not in (select pid from pool_p)").fetchone()[0]
assert bad == 0, f"{bad} excluded persons are not in the old pool — the network route has another source"

rows = con.execute("""
  select e.pid,
         case when e.pid in (select pid from rej_p) then 'rejected_in_2026-08-09_verification'
              when e.pid not in (select pid from r994_p) then 'removed_in_2026-07-20_roster_cleaning'
              else 'other' end as category,
         r.rcause as reject_cause,
         (select count(distinct event_id) from f1 where f1.pid = e.pid) as p1_events,
         (select count(distinct event_id) from f2 where f2.pid = e.pid) as p2_events
  from excl e left join rej_p r using(pid) left join pool_p p using(pid)
  order by category, e.pid""").fetchall()
excluded = {r[0] for r in rows}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "frames").mkdir(exist_ok=True)
with open(OUT / "excluded_persons.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    # public package: no display_name column (a person's name); the private original wrote one
    w.writerow(["person_id", "category", "reject_cause", "p1_events", "p2_events"])
    w.writerows(rows)


def filter_frame(src, dst, idcol, prefix):
    """Keep every line whose person is not excluded; kept lines are copied byte for byte."""
    n_in = n_out = 0
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        header = fi.readline()
        fo.write(header)
        cols = header.decode().rstrip("\r\n").split(",")
        k = cols.index(idcol)
        for line in fi:
            n_in += 1
            pid = prefix + line.decode().split(",")[k]
            if pid not in excluded:
                fo.write(line)
                n_out += 1
    return n_in, n_out


p1_in, p1_out = filter_frame(F1, OUT / "frames/p1_frame_econ_verified.csv", "incumbent_person_id", "")
p2_in, p2_out = filter_frame(F2, OUT / "frames/p2_becoming_econ_verified.csv", "pid", "P_")

# gate 4: filtered = original minus exactly the excluded persons' lines
for t, n_in, n_out in (("f1", p1_in, p1_out), ("f2", p2_in, p2_out)):
    n_ex = con.execute(f"select count(*) from {t} where pid in (select pid from excl)").fetchone()[0]
    assert n_in - n_out == n_ex, f"{t}: dropped {n_in - n_out} lines, expected {n_ex}"


def summary(t, path):
    q = lambda s: con.execute(s).fetchone()[0]
    return {
        "rows_in": q(f"select count(*) from {t}"),
        "rows_excluded": q(f"select count(*) from {t} where pid in (select pid from excl)"),
        "persons_in": q(f"select count(distinct pid) from {t}"),
        "persons_excluded": q(f"select count(distinct pid) from {t} where pid in (select pid from excl)"),
        "relations_in": q(f"select count(distinct pid||event_id) from {t}"),
        "relations_excluded": q(f"select count(distinct pid||event_id) from {t} where pid in (select pid from excl)"),
        "events_in": q(f"select count(distinct event_id) from {t}"),
        "events_touched": q(f"select count(distinct event_id) from {t} where pid in (select pid from excl)"),
        "events_after": q(f"select count(distinct event_id) from {t} where pid not in (select pid from excl)"),
        "network_route_persons_in": q(f"select count(distinct pid) from {t} where channel in ('network','both')"),
        "filtered_frame": str(path.relative_to(REPO)),
    }


cats = {}
for r in rows:
    cats[r[1]] = cats.get(r[1], 0) + 1
report = {
    "generated": "2026-09-13",
    "rule": "drop incumbents whose person_id (via the 2026-07-16 11-school person map) is not on the "
            "2026-08-09 verified economics roster; all such incumbents enter through the network route only",
    "verified_persons": con.execute("select count(*) from ver_p").fetchone()[0],
    "old_pool_persons": con.execute("select count(*) from pool_p").fetchone()[0],
    "verified_persons_not_in_old_pool": con.execute(
        "select count(*) from ver_p where pid not in (select pid from pool_p)").fetchone()[0],
    "excluded_persons": len(excluded),
    "excluded_by_category": cats,
    "panel1": summary("f1", OUT / "frames/p1_frame_econ_verified.csv"),
    "panel2": summary("f2", OUT / "frames/p2_becoming_econ_verified.csv"),
    "gates": ["roster-route persons all verified (both frames)", "excluded persons network-route only",
              "excluded persons all in old pool", "filtered frames = original minus excluded lines"],
    "inputs_sha256": {str(p): sha(p) for p in [F1, F2, VER, PM, REJ, R994] + POOL},
}
(OUT / "build_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
print(json.dumps({k: report[k] for k in ("verified_persons", "old_pool_persons", "verified_persons_not_in_old_pool",
                                          "excluded_persons", "excluded_by_category", "panel1", "panel2")}, indent=1))
