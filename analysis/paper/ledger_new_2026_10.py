#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ledger_new_2026_10.py — the two numbers the supervisor's 2026-09-21 round asked for, per discipline,
computed from the frozen frames and the extraction tables (nothing in the frames records them):

  1. one-hop share: of the incumbents an arrival exposes, how many are the star's DIRECT
     (pre-arrival) coauthors, i.e. share a work with the star published in or before T_e - 1 —
     prodlib's deg1 rule (build_pairs: p1.year <= t-1 AND p2.year <= t-1 on a common work_id, on the
     person-level edge table = snapshot edges ∪ supplement, econ folded through the U2 person map).
     Reported over every incumbent x event pair of the Panel 1 frame, and within the network channel
     (channel in {network, both}: the incumbents who are in the star's two-hop network at all);
     everyone else in that channel is two hops away by construction.
  2. subfields: the support of the similarity dose per discipline — the distinct OpenAlex subfields
     that appear in the pre-arrival works (year <= T_e - 1) of the frame's incumbents and stars —
     split into the discipline's own field (subfield ids 20xx economics, 16xx chemistry, 26xx
     mathematics) and the rest; plus, for context, how many subfields of the own field exist in the
     whole extraction table (the taxonomy as the snapshot instantiates it).

Inputs: the Panel 1 frame p1_frame_{field}.csv (incumbent_person_id, star_person_id, event_id, year,
post, channel), the October event tables (arrival years; a cross-check against the frame's first
post year), the extraction tables named in pipeline/frames/cal2026-10/configs/{field}.json
(${DERIVED} = <ssd_root>/derived), the same supplements stage.py feeds prodlib, and (econ) the U2
person map. Output: output/paper/data_numbers_new_2026-10.json, sorted keys, with input hashes.

    ledger_new_2026_10.py --frames "data/cal2026-10/frames_{field}" --fields chemistry math_stats \
        --control-db chemistry=/path/to/prodlib/run/_work/prod.db
--control-db cross-checks rule 1 against prodlib's own hop1 table for that run (must be EQUAL).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

import duckdb

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths   # noqa: E402
from analysis.lib import canon   # noqa: E402

FIELD_CODE = {"econ": "20", "chemistry": "16", "math_stats": "26"}
_P = load_paths()
SUPPLEMENTS = {   # exactly what pipeline/frames/cal2026-10/stage.py concatenates for prodlib
    # R1 F7: the canon-rooted two through canon.key (October: the same repo-relative strings)
    "econ": [canon.key(_P["raw_verified"] / "edges_supplement_econ_fnfix.jsonl"),
             "data/cal2026-08-28/edges_supplement_cal2026-08-28.jsonl",
             canon.key(_P["cal"] / "edges_supplement_star_id_corrections_2026-10.jsonl")],
    "chemistry": ["data/cal2026-08-28/edges_supplement_cal2026-08-28.jsonl"],
    "math_stats": ["data/cal2026-08-28/edges_supplement_cal2026-08-28.jsonl"],
}


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def config(field: str, derived: pathlib.Path) -> dict:
    c = json.loads((REPO / "pipeline/frames/cal2026-10/configs" / f"{field}.json").read_text(encoding="utf-8"))
    def r(s): return s.replace("${DERIVED}", str(derived))
    out = {"edges_glob": r(c["snapshot"]["edges_glob"]), "works_glob": r(c["snapshot"]["works_glob"])}
    pm = c.get("person_map", {})
    out["person_map"] = r(pm["path"]) if pm.get("mode") == "parquet" else None
    return out


def arrival_years(events_dir: pathlib.Path, field: str) -> dict[str, int]:
    import csv
    p = events_dir / f"events_{field}_cal2026-10.csv"
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if field == "econ":
        return {r["event_id"]: int(r["arrival_year"]) for r in rows}
    return {f"{r['author_id']}:{r['school']}": int(r["arrival_corrected"]) for r in rows}


def one_field(field: str, frames_dir: pathlib.Path, events_dir: pathlib.Path, derived: pathlib.Path,
              control_db: pathlib.Path | None) -> dict:
    cfg = config(field, derived)
    p1 = frames_dir / f"p1_frame_{field}.csv"
    con = duckdb.connect()
    con.execute(f"CREATE TABLE p1 AS SELECT incumbent_person_id AS pid, star_person_id AS star, event_id, "
                f"CAST(year AS INTEGER) AS year, CAST(post AS VARCHAR) AS post, channel FROM read_csv_auto('{p1}', header=true, all_varchar=true)")
    # members: incumbent x event with its channel; T_e = first post year of the event in the frame
    con.execute("CREATE TABLE members AS SELECT DISTINCT pid, star, event_id, channel FROM p1")
    con.execute("CREATE TABLE te AS SELECT event_id, min(year) AS t_e FROM p1 WHERE lower(post) IN ('true','1') GROUP BY 1")
    te = dict(con.execute("SELECT event_id, t_e FROM te").fetchall())
    ay = arrival_years(events_dir, field)
    mism = {e: (te.get(e), ay.get(e)) for e in set(te) | set(ay) if te.get(e) != ay.get(e)}
    if mism:
        raise SystemExit(f"{field}: frame first-post year != event-table arrival for {mism}")
    n_chan = dict(con.execute("SELECT channel, count(*) FROM members GROUP BY 1").fetchall())

    # relevant author ids: members + stars, through the person map for econ
    if cfg["person_map"]:
        con.execute(f"CREATE TABLE pm AS SELECT author_id, person_id FROM read_parquet('{cfg['person_map']}')")
        con.execute("CREATE TABLE persons AS SELECT DISTINCT pid AS person_id FROM members UNION SELECT DISTINCT star FROM members")
        con.execute("CREATE TABLE rel_authors AS SELECT pm.author_id, pm.person_id FROM pm JOIN persons USING (person_id)")
        n_unmapped_persons = con.execute("SELECT count(*) FROM persons WHERE person_id NOT IN (SELECT person_id FROM rel_authors)").fetchone()[0]
        # a person id of the frame with no map row is a bare `P_<author>` (prodlib's fold of an unmapped author)
        con.execute("INSERT INTO rel_authors SELECT substr(person_id, 3), person_id FROM persons WHERE person_id NOT IN (SELECT person_id FROM rel_authors) AND person_id LIKE 'P_%'")
    else:
        con.execute("CREATE TABLE rel_authors AS SELECT DISTINCT pid AS author_id, pid AS person_id FROM members UNION SELECT DISTINCT star, star FROM members")
        n_unmapped_persons = 0
    # snapshot edges of the relevant authors ∪ the supplement rows (prodlib's `merged`), person level
    con.execute(f"""CREATE TABLE snap AS
        SELECT e.work_id, e.author_id, CAST(e.publication_year AS INTEGER) AS year
        FROM read_parquet('{cfg['edges_glob']}', hive_partitioning=0) e
        JOIN rel_authors r ON e.author_id = r.author_id""")
    sup_rows = []
    for rel in SUPPLEMENTS[field]:
        for ln in canon.resolve(rel).read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            j = json.loads(ln)
            for a in j.get("authors", []):
                sup_rows.append((j["work_id"], a, j.get("publication_year")))
    con.execute("CREATE TABLE sup (work_id VARCHAR, author_id VARCHAR, year INTEGER)")
    con.executemany("INSERT INTO sup VALUES (?, ?, ?)", sup_rows)
    con.execute("""CREATE TABLE pedges AS
        SELECT DISTINCT m.work_id, r.person_id, m.year FROM
          (SELECT work_id, author_id, year FROM snap UNION SELECT work_id, author_id, year FROM sup) m
        JOIN rel_authors r ON m.author_id = r.author_id""")
    # rule 1: one hop iff a common work with year <= T_e - 1
    con.execute("""CREATE TABLE onehop AS
        SELECT DISTINCT m.pid, m.event_id
        FROM members m JOIN te USING (event_id)
        JOIN pedges s ON s.person_id = m.star
        JOIN pedges o ON o.work_id = s.work_id AND o.person_id = m.pid
        WHERE s.year IS NOT NULL AND o.year IS NOT NULL AND s.year <= te.t_e - 1 AND o.year <= te.t_e - 1""")
    q = lambda sql: con.execute(sql).fetchone()[0]
    n_all = q("SELECT count(*) FROM members")
    n_net = q("SELECT count(*) FROM members WHERE channel IN ('network','both')")
    n_netonly = q("SELECT count(*) FROM members WHERE channel = 'network'")
    n_1 = q("SELECT count(*) FROM onehop")
    n_1_net = q("SELECT count(*) FROM onehop h JOIN members m USING (pid, event_id) WHERE m.channel IN ('network','both')")
    n_1_netonly = q("SELECT count(*) FROM onehop h JOIN members m USING (pid, event_id) WHERE m.channel = 'network'")
    n_1_dept = q("SELECT count(*) FROM onehop h JOIN members m USING (pid, event_id) WHERE m.channel = 'dept_only'")
    ev_1 = q("SELECT count(DISTINCT event_id) FROM onehop")
    res = {
        "n_incumbent_event_pairs": n_all, "n_incumbents": q("SELECT count(DISTINCT pid) FROM members"),
        "n_events": q("SELECT count(DISTINCT event_id) FROM members"),
        "channel_counts": {k: int(v) for k, v in sorted(n_chan.items())},
        "onehop_pairs": n_1, "onehop_pairs_network_channel": n_1_net, "onehop_pairs_network_only": n_1_netonly,
        "onehop_pairs_dept_only_channel": n_1_dept,
        "share_onehop_all": round(n_1 / n_all, 4) if n_all else None,
        "share_onehop_network_channel": round(n_1_net / n_net, 4) if n_net else None,
        "share_onehop_network_only": round(n_1_netonly / n_netonly, 4) if n_netonly else None,
        "share_twohop_network_channel": round(1 - n_1_net / n_net, 4) if n_net else None,
        "events_with_a_onehop_incumbent": ev_1,
        "unmapped_frame_persons": int(n_unmapped_persons),
    }
    # rule 2: subfields in the pre-arrival works of the frame's persons
    con.execute(f"""CREATE TABLE works AS
        SELECT w.work_id, regexp_replace(CAST(w.subfield_id AS VARCHAR), '^.*/', '') AS sf, CAST(w.publication_year AS INTEGER) AS year
        FROM read_parquet('{cfg['works_glob']}', hive_partitioning=0) w
        WHERE w.work_id IN (SELECT work_id FROM pedges)""")
    con.execute("""CREATE TABLE prework AS
        SELECT DISTINCT w.work_id, w.sf
        FROM pedges p JOIN members m ON p.person_id IN (m.pid, m.star) JOIN te USING (event_id)
        JOIN works w ON w.work_id = p.work_id
        WHERE w.year IS NOT NULL AND w.year <= te.t_e - 1 AND w.sf IS NOT NULL AND w.sf <> ''""")
    code = FIELD_CODE[field]
    n_sf = q("SELECT count(DISTINCT sf) FROM prework")
    n_sf_own = q(f"SELECT count(DISTINCT sf) FROM prework WHERE sf LIKE '{code}%' AND length(sf) = 4")
    n_w = q("SELECT count(DISTINCT work_id) FROM prework")
    n_w_own = q(f"SELECT count(DISTINCT work_id) FROM prework WHERE sf LIKE '{code}%' AND length(sf) = 4")
    own_list = [r[0] for r in con.execute(f"SELECT DISTINCT sf FROM prework WHERE sf LIKE '{code}%' AND length(sf) = 4 ORDER BY 1").fetchall()]
    n_tax = q(f"""SELECT count(DISTINCT regexp_replace(CAST(subfield_id AS VARCHAR), '^.*/', ''))
                  FROM read_parquet('{cfg['works_glob']}', hive_partitioning=0)
                  WHERE regexp_replace(CAST(subfield_id AS VARCHAR), '^.*/', '') LIKE '{code}%'
                    AND length(regexp_replace(CAST(subfield_id AS VARCHAR), '^.*/', '')) = 4""")
    res.update({
        "subfields_in_dose_support": n_sf, "subfields_in_dose_support_own_field": n_sf_own,
        "own_field_subfield_ids_in_support": own_list,
        "prearrival_works": n_w, "prearrival_works_own_field": n_w_own,
        "share_prearrival_works_own_field": round(n_w_own / n_w, 4) if n_w else None,
        "own_field_subfields_in_extraction_table": n_tax, "own_field_code": code,
    })
    # control: prodlib's own hop1 table (star, mid, y1 = earliest common work year)
    if control_db:
        con.execute(f"ATTACH '{control_db}' AS ctl (READ_ONLY)")
        got = set(con.execute("SELECT star || '|' || pid || '|' || event_id FROM onehop JOIN members USING (pid, event_id)").fetchall())
        exp = set(con.execute("""SELECT m.star || '|' || m.pid || '|' || m.event_id
                                 FROM members m JOIN te USING (event_id)
                                 JOIN ctl.hop1 h ON h.star = m.star AND h.mid = m.pid
                                 WHERE h.y1 <= te.t_e - 1""").fetchall())
        res["control_prodlib_hop1"] = {"db": str(control_db), "compare": "EQUAL" if got == exp else "DIFF",
                                       "only_here": sorted(x[0] for x in got - exp)[:20], "only_prodlib": sorted(x[0] for x in exp - got)[:20]}
    res["_inputs"] = {"p1_frame": str(p1.relative_to(REPO)) if p1.is_relative_to(REPO) else str(p1), "p1_sha256": sha(p1),
                      "events": canon.key(_P["cal"] / f"events_{field}_cal2026-10.csv"), "events_sha256": sha(events_dir / f"events_{field}_cal2026-10.csv"),
                      "edges_glob": cfg["edges_glob"], "works_glob": cfg["works_glob"], "person_map": cfg["person_map"],
                      "supplements": {rel: sha(canon.resolve(rel)) for rel in SUPPLEMENTS[field]},
                      "snapshot_edges_of_relevant_authors": q("SELECT count(*) FROM snap"), "supplement_rows_read": len(sup_rows)}
    con.close()
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--frames", default=None, help="frames dir; `{field}` is substituted per field (default: paths.yaml frames)")
    ap.add_argument("--fields", nargs="+", default=["econ", "chemistry", "math_stats"])
    ap.add_argument("--events-dir", default=str(_P["cal"]))   # R1 F7: the cal root from config
    ap.add_argument("--control-db", action="append", default=[], help="field=path to a prodlib run's _work/prod.db")
    ap.add_argument("--out", default=None)
    ap.add_argument("--merge", action="store_true", help="update the fields given inside an existing --out instead of rewriting it")
    a = ap.parse_args(argv)
    P = load_paths()
    derived = pathlib.Path(P["ssd_root"]) / "derived"
    out = pathlib.Path(a.out) if a.out else P["output"] / "paper" / "data_numbers_new_2026-10.json"
    ctl = {kv.split("=", 1)[0]: pathlib.Path(kv.split("=", 1)[1]) for kv in a.control_db}
    res = json.loads(out.read_text(encoding="utf-8")) if (a.merge and out.exists()) else {}
    for f in a.fields:
        fd = pathlib.Path((a.frames or str(P["frames"])).replace("{field}", f))
        res[f] = one_field(f, fd, pathlib.Path(a.events_dir), derived, ctl.get(f))
        print(f, json.dumps({k: res[f][k] for k in ("n_incumbent_event_pairs", "channel_counts", "share_onehop_all", "share_onehop_network_channel",
                                                    "subfields_in_dose_support", "subfields_in_dose_support_own_field", "own_field_subfields_in_extraction_table")}))
        if "control_prodlib_hop1" in res[f]:
            print(f, "control vs prodlib hop1:", res[f]["control_prodlib_hop1"]["compare"])
    res["_generator"] = "analysis/paper/ledger_new_2026_10.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
