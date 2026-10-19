# -*- coding: utf-8 -*-
"""Missing-outcome persons at M scale (R1 P3c-e items N3 + J0-MEAS.3i, one module).

A frame person-year with publications needs an outcome source. Two places can lack one:

ECONOMICS (`04_rebuild_y.py`): the outcome comes from the frozen 2026-08-09 units table or from the
works-by-author patch the chain reads (the shadow's PATCH_A: frozen 2026-08-13 ⧺ October supplement ⧺
any R1 supplement). A person in neither source gets
  * old-event rows: `agg_missing` in 04's C-PC anchor -> PASS False, exit 2 (class
    `old_event_rows_blocking`);
  * prodlib/REGEN-event rows: y = NA written silently (class `prodlib_event_rows_written_NA`).
`agg_missing_r1()` is October's `econ920_lib.agg_missing_persons()` with every path passed in: that
function hard-reads the frozen 08-13 patch only and would wrongly list the two October-supplement
persons (P_A5046503193, P_A5065862323). With the legacy units table and patch it returns October's
dict exactly (tested). Coverage is person level, as October's: a person with any row in either source
counts as covered.

CHEMISTRY / MATHS (`20_rebuild_y_gold.py`): the outcome is the person-year aggregate of own edges x
works rows under the alias closure of the person map. `chemmath_agg_missing()` lists frame rows with
pub_count > 0 whose (person, year) has no such row - the y step's `agg_missing` transition, which the
CLI cross-checks against the y step's own report (swap '<variant>_new'.transition.agg_missing).
Persons with no own edge x works row in any year are counted, report only.

GATE: `coverage_gate(result, mode, round)` -> (code, ids)
  mode 'report' (B0, F9 switch agg_missing off) -> always 'OK' (the ids are still recorded);
  mode 'stop'   (M) -> 'OK' | 'AGG_MISSING' (round 1: STOP, fetch on the Mac, resume) |
                       'AGG_MISSING_AFTER_FETCH' (round >= 2: no second fetch loop; the rows stay NA
                       and are counted for the change note; the build goes on) |
                       'CROSSCHECK_FAIL' (chem/maths only: this count disagrees with the y step).
`write_report()` writes STAGE_OUT/stop_report_<name>.json and returns 3 for a STOP code, else
STAGE_OUT/report_<name>.json and 0. The report is what run_stages carries into summary.json, the one
file that may leave S3 for the Mac: codes, counts, sha256s, OpenAlex ids ('P_A' + digits) and event
ids only - never a path, never a name (an id of any other shape raises ValueError).

CLI (stage `coverage_chemmath`, J1a):
  missing_persons.py chemmath --frames DIR [DIR ...] --pmap P --edges GLOB --works GLOB --out STAGE_OUT
                              [--mode stop|report] [--round N]
  Each DIR holds the y step's analysis_frame_<field>_new_*.csv and g_yrebuild_<field>.json. Writes
  report_coverage.json (exit 0) or stop_report_coverage.json (exit 3).
Paths only via arguments; this module reads nothing else.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import re
import sys

ECON_CLASSES = ("old_event_rows_blocking", "prodlib_event_rows_written_NA")
MODES = ("report", "stop")
STOP_CODES = frozenset({"AGG_MISSING", "CROSSCHECK_FAIL"})
EXIT_STOP = 3
_ID = re.compile(r"^P_A\d+$")
_BARE = re.compile(r"^A\d+$")
_FRAME_RE = re.compile(r"^analysis_frame_(.+?)_new_.*\.csv$")
_DROP_KEYS = frozenset({"path", "out"})


def sha(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _q(p) -> str:
    """A path or glob as a duckdb string literal body."""
    return str(p).replace("'", "''")


def norm_id(pid: str) -> str:
    """'P_A<digits>' for an OpenAlex author id with or without the P_ prefix; anything else raises."""
    if _ID.match(pid):
        return pid
    if _BARE.match(pid):
        return "P_" + pid
    raise ValueError(f"not an OpenAlex author id: {pid!r}")


# ---------------------------------------------------------------------------------------------
# economics
# ---------------------------------------------------------------------------------------------

def agg_missing_r1(pre_y, units_parquet, patch_files: list, prodlib_events: set, added_ids=None) -> dict:
    """October's econ920_lib.agg_missing_persons with every path explicit.

    pre_y: the pre-y econ frame (after the post-filter / V3-NET filter); units_parquet: the frozen
    econ_units_2026-08-09.parquet; patch_files: the works-by-author patch file(s) 04 reads (the shadow's
    PATCH_A, or its parts); prodlib_events: event ids 04 writes NA for; added_ids: 'P_A…' ids of the
    roster additions (October read data/cal2026-10/roster_added_2026-10.csv; None = no set, count 0)."""
    import duckdb                                                        # noqa: PLC0415
    pre_y, units = pathlib.Path(pre_y), pathlib.Path(units_parquet)
    patches = [pathlib.Path(p) for p in patch_files]
    if not patches:
        raise ValueError("agg_missing_r1: at least one patch file")
    con = duckdb.connect()
    u = {t[0] for t in con.execute(f"select distinct incumbent_person_id from read_parquet('{_q(units.as_posix())}')").fetchall()}
    pa: set[str] = set()
    for p in patches:
        with open(p, encoding="utf-8") as fh:
            pa |= {"P_" + json.loads(ln)["author_id"] for ln in fh if ln.strip()}
    rows = con.execute(f"select incumbent_person_id, year, event_id, channel, pub_count from "
                       f"read_csv_auto('{_q(pre_y.as_posix())}', all_varchar=true) "
                       f"where pub_count not in ('', '0', '0.0')").fetchall()
    con.close()
    added = set(added_ids or ())
    out: dict = {}
    for cls, pred in ((ECON_CLASSES[0], lambda r: r[2] not in prodlib_events),
                      (ECON_CLASSES[1], lambda r: r[2] in prodlib_events)):
        bad = [r for r in rows if pred(r) and r[0] not in u and r[0] not in pa]
        persons = sorted({r[0] for r in bad})
        out[cls] = {"rows": len(bad), "persons": persons, "person_years": len({(r[0], r[1]) for r in bad}),
                    "events": sorted({r[2] for r in bad}),
                    "by_channel": {c: sum(1 for r in bad if r[3] == c) for c in ("network", "dept_only", "both")},
                    "persons_in_roster_added_2026-10": sum(1 for p_ in persons if p_ in added)}
    out["units"] = {"path": str(units), "sha256": sha(units), "persons": len(u)}
    if len(patches) == 1:
        out["patch"] = {"path": str(patches[0]), "sha256": sha(patches[0]), "persons": len(pa)}
    else:
        out["patch"] = {"path": [str(p) for p in patches], "sha256": [sha(p) for p in patches], "persons": len(pa)}
    return out


# ---------------------------------------------------------------------------------------------
# chemistry / maths
# ---------------------------------------------------------------------------------------------

def _fnum(s):
    return None if s in ("", None) else float(s)


def read_frame(frame_csv) -> tuple[list[str], list[list[str]]]:
    """The y step's own parser: split on \\n, strip \\r (07-24 CRLF leftovers)."""
    with open(frame_csv, "rb") as fh:
        hdr = next(csv.reader([fh.readline().decode().rstrip("\n").replace("\r", "")]))
        rows = [next(csv.reader([ln.decode().rstrip("\n").replace("\r", "")])) for ln in fh]
    return hdr, rows


def chemmath_agg_missing(frame_csv, pmap, edges_glob, works_glob) -> dict:
    """Frame rows with pub_count > 0 whose (person, year) has no own edge x works row under any alias
    of the person map (20_rebuild_y_gold's aggregate key: edges.publication_year not NULL, work_id in
    the works table). Persons with no such row in any year: counted, report only."""
    import duckdb                                                        # noqa: PLC0415
    hdr, rows = read_frame(frame_csv)
    ix = {c: i for i, c in enumerate(hdr)}
    for c in ("incumbent_person_id", "year", "event_id", "pub_count"):
        if c not in ix:
            raise ValueError(f"{frame_csv}: no column {c!r}")
    pids = sorted({r[ix["incumbent_person_id"]] for r in rows})
    for p in pids:
        norm_id(p)                                                       # ids only, before any SQL
    con = duckdb.connect()
    con.execute("CREATE TEMP TABLE needp(bare VARCHAR)")
    if pids:
        con.execute("INSERT INTO needp VALUES " + ",".join(f"('{p}')" for p in pids))
    pm, ed, wk = _q(pmap), _q(edges_glob), _q(works_glob)
    keys = con.execute(f"""
        WITH canon AS (SELECT n.bare, m.person_id FROM needp n JOIN read_parquet('{pm}') m ON m.author_id = n.bare),
        alias AS (SELECT c.bare AS person_id, m2.author_id
                  FROM canon c JOIN read_parquet('{pm}') m2 ON m2.person_id = c.person_id
                  UNION ALL
                  SELECT bare, bare FROM needp WHERE bare NOT IN (SELECT bare FROM canon)),
        own AS (SELECT DISTINCT a.person_id AS pid, e.work_id, e.publication_year AS yr
                FROM read_parquet('{ed}', hive_partitioning=false) e JOIN alias a ON e.author_id = a.author_id
                WHERE e.publication_year IS NOT NULL),
        w AS (SELECT DISTINCT work_id FROM read_parquet('{wk}', hive_partitioning=false)
              WHERE work_id IN (SELECT work_id FROM own))
        SELECT DISTINCT own.pid, CAST(own.yr AS INTEGER) FROM own JOIN w USING (work_id)""").fetchall()
    con.close()
    agg = {(p, int(y)) for p, y in keys}
    with_works = {p for p, _ in agg}
    ch = ix.get("channel")
    papers = [r for r in rows if (pc := _fnum(r[ix["pub_count"]])) is not None and pc != 0]
    bad = [r for r in papers if (r[ix["incumbent_person_id"]], int(float(r[ix["year"]]))) not in agg]
    chans = sorted({r[ch] for r in rows}) if ch is not None else []
    return {
        "frame_sha256": sha(frame_csv),
        "rows_with_papers": len(papers),
        "missing": {
            "rows": len(bad),
            "persons": sorted({norm_id(r[ix["incumbent_person_id"]]) for r in bad}),
            "person_years": len({(r[ix["incumbent_person_id"]], int(float(r[ix["year"]]))) for r in bad}),
            "events": sorted({r[ix["event_id"]] for r in bad}),
            "by_channel": {c: sum(1 for r in bad if r[ch] == c) for c in chans} if ch is not None else {},
        },
        "persons_without_works": {"count": sum(1 for p in pids if p not in with_works)},
    }


def y_step_agg_missing(report: dict):
    """The y step's own agg_missing row count for the main (new-denominator) frame, or None."""
    swap = report.get("swap") or {}
    for k in ("none_new", "gold_new"):
        if k in swap:
            return swap[k]["transition"]["agg_missing"]
    news = [k for k in swap if k.endswith("_new")]
    return swap[news[0]]["transition"]["agg_missing"] if len(news) == 1 else None


def chemmath_dirs(frame_dirs, pmap, edges_glob, works_glob) -> dict:
    """Every analysis_frame_<field>_new_*.csv in the given dirs, cross-checked against the y step's
    g_yrebuild_<field>.json beside it: {'fields': {field: result + cross_check}}."""
    fields: dict = {}
    for d in map(pathlib.Path, frame_dirs):
        frames = sorted(p for p in d.glob("analysis_frame_*_new_*.csv") if _FRAME_RE.match(p.name))
        if not frames:
            raise SystemExit(f"COVERAGE_STOP no analysis_frame_<field>_new_*.csv in {d}")
        for fr in frames:
            field = _FRAME_RE.match(fr.name).group(1)
            if field in fields:
                raise SystemExit(f"COVERAGE_STOP two frames for {field}")
            res = chemmath_agg_missing(fr, pmap, edges_glob, works_glob)
            rp = d / f"g_yrebuild_{field}.json"
            if rp.is_file():
                y = y_step_agg_missing(json.loads(rp.read_text(encoding="utf-8")))
                status = "EQUAL" if y == res["missing"]["rows"] else "MISMATCH"
            else:
                y, status = None, "NO_REPORT"
            res["cross_check"] = {"status": status, "y_step_agg_missing": y, "rows": res["missing"]["rows"]}
            fields[field] = res
    return {"fields": fields}


# ---------------------------------------------------------------------------------------------
# gate + report
# ---------------------------------------------------------------------------------------------

def _person_lists(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "persons" and isinstance(v, list):
                yield v
            else:
                yield from _person_lists(v)


def coverage_gate(result: dict, mode: str, round: int) -> tuple[str, list[str]]:   # noqa: A002
    """(code, ids): ids = every listed person ('P_A…'), code per the module docstring."""
    if mode not in MODES:
        raise ValueError(f"mode {mode!r} is not one of {MODES}")
    if int(round) < 1:
        raise ValueError(f"round {round!r} < 1")
    ids = sorted({norm_id(p) for lst in _person_lists(result) for p in lst})
    if mode == "report":
        return "OK", ids
    if any(f.get("cross_check", {}).get("status") != "EQUAL" for f in (result.get("fields") or {}).values()):
        return "CROSSCHECK_FAIL", ids
    if not ids:
        return "OK", ids
    return ("AGG_MISSING" if int(round) == 1 else "AGG_MISSING_AFTER_FETCH"), ids


def _scrub(obj):
    """Drop paths; normalise person lists to ids."""
    if isinstance(obj, dict):
        return {k: (sorted(norm_id(p) for p in v) if k == "persons" and isinstance(v, list) else _scrub(v))
                for k, v in obj.items() if k not in _DROP_KEYS}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def summary(result: dict, code: str, ids: list[str], *, mode: str, round: int) -> dict:  # noqa: A002
    """The report body (ids, counts, codes, sha256s; no paths, no names)."""
    out = {"code": code, "mode": mode, "round": int(round), "n_persons": len(ids), "persons": list(ids)}
    if "fields" in result:
        out["fields"] = _scrub(result["fields"])
        return out
    classes = {k: v for k, v in result.items() if isinstance(v, dict) and isinstance(v.get("persons"), list)}
    out["classes"] = {k: {**_scrub(v), "n_persons": len(v["persons"])} for k, v in classes.items()}
    out["inputs"] = _scrub({k: v for k, v in result.items() if k not in classes})
    return out


def write_report(stage_out, name: str, result: dict, *, mode: str, round: int) -> int:  # noqa: A002
    """STAGE_OUT/stop_report_<name>.json -> 3 for a STOP code, else STAGE_OUT/report_<name>.json -> 0."""
    code, ids = coverage_gate(result, mode, round)
    body = summary(result, code, ids, mode=mode, round=round)
    stage_out = pathlib.Path(stage_out)
    stage_out.mkdir(parents=True, exist_ok=True)
    stop = code in STOP_CODES
    for stale in (f"report_{name}.json", f"stop_report_{name}.json"):
        (stage_out / stale).unlink(missing_ok=True)
    target = stage_out / (f"stop_report_{name}.json" if stop else f"report_{name}.json")
    target.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RESULT {code} persons={len(ids)} -> {target.name}", flush=True)
    return EXIT_STOP if stop else 0


def econ_gate(stage_out, pre_y, units_parquet, patch_files, prodlib_events, *, mode: str, round: int,  # noqa: A002
              added_ids=None, name: str = "agg_missing") -> tuple[int, dict]:
    """For the econ wrapper: agg_missing_r1 + write_report. Returns (exit code, full result)."""
    res = agg_missing_r1(pre_y, units_parquet, patch_files, prodlib_events, added_ids=added_ids)
    return write_report(stage_out, name, res, mode=mode, round=round), res


# ---------------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="missing_persons.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chemmath", help="coverage of the chem/maths frames after the y step")
    c.add_argument("--frames", nargs="+", required=True, help="dirs holding the y step's frame + report")
    c.add_argument("--pmap", required=True)
    c.add_argument("--edges", required=True, help="parquet glob of the u1 authorship edges")
    c.add_argument("--works", required=True, help="parquet glob of the u1 works")
    c.add_argument("--out", required=True, help="STAGE_OUT")
    c.add_argument("--mode", choices=MODES, default="stop")
    c.add_argument("--round", type=int, default=1)
    a = ap.parse_args(argv)
    res = chemmath_dirs(a.frames, a.pmap, a.edges, a.works)
    return write_report(a.out, "coverage", res, mode=a.mode, round=a.round)


if __name__ == "__main__":
    sys.exit(main())
