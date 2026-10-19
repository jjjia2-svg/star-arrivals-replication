#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""econ920/fetch_patch_supplement.py — the OpenAlex works-by-author patch for the October roster
additions that `04_rebuild_y.py` cannot give a y to (build_report_econ920_2026-10.json ->
october.chain.p1_econ.agg_missing.old_event_rows_blocking.persons: persons in neither the frozen
2026-08-09 units table nor the 2026-08-13 API patch). Same remedy as 2026-08-13 for the 112
pool-outside persons: one row per (author, work) in the EXACT shape of
`econ_final_2026-08-13/patch/works_by_author.jsonl` —
  {"author_id", "work_id", "publication_year", "fwci", "cited_by_count", "subfield_id", "n_authors", "author_ids"}
— fetched live (`filter=author.id:<id>`, cursor pages of 200, the 70_prep retry ladder and request
log of pipeline/stars/caliber_2026-08-28/supplement_fetch.py, no api key in the log). The union
rung then takes these persons API-first (00_build_frame_econ920_cal.py "API first") and 04 aggregates
them from the patch, so both sides count the same works.

    setup/.venv/bin/python pipeline/frames/cal2026-10/econ920/fetch_patch_supplement.py --execute
Outputs (frozen into data/cal2026-10/patch_supplement_2026-10/):
  works_by_author_supplement_2026-10.jsonl      the patch rows, profile order
  api_request_log_patch_supplement_2026-10.jsonl one line per HTTP request
  patch_supplement_report_2026-10.json           persons, counts, sha256s, snapshot overlap (measure)
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "pipeline/stars/caliber_2026-08-28"))
import supplement_fetch as sf                                       # noqa: E402
from analysis.lib.paths import load_paths                           # noqa: E402

OUT = REPO / "data/cal2026-10/patch_supplement_2026-10"
REPORT = REPO / "data/cal2026-10/frames_econ/build_report_econ920_2026-10.json"
SELECT = "id,publication_year,fwci,cited_by_count,primary_topic,authorships"
KEYS = ("author_id", "work_id", "publication_year", "fwci", "cited_by_count", "subfield_id", "n_authors", "author_ids")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def blocking_persons() -> list[str]:
    j = json.loads(REPORT.read_text(encoding="utf-8"))
    return list(j["october"]["chain"]["p1_econ"]["agg_missing"]["old_event_rows_blocking"]["persons"])


def patch_row(aid: str, w: dict) -> dict:
    authors = [sf.short((a.get("author") or {}).get("id", "")) for a in w.get("authorships", [])]
    authors = [a for a in authors if a]
    sub = ((w.get("primary_topic") or {}).get("subfield") or {}).get("id")
    return {"author_id": aid, "work_id": sf.short(w["id"]), "publication_year": w.get("publication_year"),
            "fwci": w.get("fwci"), "cited_by_count": w.get("cited_by_count"),
            "subfield_id": sf.short(sub) if sub else None, "n_authors": len(authors), "author_ids": authors}


def fetch_author(aid: str, key: str | None, log) -> list[dict]:
    rows, cursor = [], "*"
    while cursor:
        params = {"filter": f"author.id:{aid}", "per-page": 200, "cursor": cursor, "select": SELECT, "mailto": sf.MAILTO}
        if key:
            params["api_key"] = key
        js = sf._get(params, log, seed=aid)
        rows.extend(patch_row(aid, w) for w in js.get("results", []))
        cursor = js.get("meta", {}).get("next_cursor")
        time.sleep(0.15)
    return rows


def snapshot_overlap(aid: str, work_ids: set[str]) -> dict:
    import duckdb                                                   # noqa: PLC0415
    P = load_paths(); g = str(pathlib.Path(P["ssd_root"]) / "derived/u1_full_11school_2026-07-16/authorship_edges/**/*.parquet")
    if not glob.glob(g, recursive=True):
        return {"measured": False}
    con = duckdb.connect()
    snap = {r[0] for r in con.execute(f"SELECT DISTINCT work_id FROM read_parquet('{g}', hive_partitioning=0) WHERE author_id = '{aid}'").fetchall()}
    con.close()
    return {"measured": True, "snapshot_works_of_author": len(snap), "api_works": len(work_ids),
            "in_both": len(snap & work_ids), "api_only": len(work_ids - snap), "snapshot_only": len(snap - work_ids)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--persons", nargs="*", default=None, help="P_<id> or <id>; default = the report's blocking persons")
    a = ap.parse_args(argv)
    persons = [p[2:] if p.startswith("P_") else p for p in (a.persons or blocking_persons())]
    if not a.execute:
        print(f"would fetch {persons} from the OpenAlex API; re-run with --execute"); return 2
    OUT.mkdir(parents=True, exist_ok=True)
    key = sf.api_key(); log = sf.RequestLog()
    rep = {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "persons": persons, "api_key_present": bool(key),
           "source_report": str(REPORT.relative_to(REPO)), "select": SELECT, "per_author": {}}
    rows = []
    for aid in persons:
        r = fetch_author(aid, key, log)
        ids = {x["work_id"] for x in r}
        rep["per_author"][aid] = {"works": len(r), "distinct_works": len(ids), "with_year": sum(1 for x in r if x["publication_year"] is not None),
                                 "with_fwci": sum(1 for x in r if x["fwci"] is not None), "with_subfield": sum(1 for x in r if x["subfield_id"]),
                                 "snapshot_overlap": snapshot_overlap(aid, ids)}
        rows.extend(r)
    out = OUT / "works_by_author_supplement_2026-10.jsonl"
    out.write_text("".join(json.dumps({k: r[k] for k in KEYS}, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    logp = OUT / "api_request_log_patch_supplement_2026-10.jsonl"
    log.write(logp)
    logged = logp.read_text(encoding="utf-8")
    assert "api_key" not in logged and (not key or key not in logged), "api key leaked into the log"
    rep["rows"] = len(rows); rep["outputs"] = {out.name: sha(out), logp.name: sha(logp)}
    (OUT / "patch_supplement_report_2026-10.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("persons", "rows", "per_author")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
