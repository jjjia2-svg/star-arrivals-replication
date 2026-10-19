#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""star_origins_extract_2026-10.py — freeze, from the OFFLINE OpenAlex snapshot on the data disk, the
small inputs the appendix world map (analysis/paper/fig_star_origins.py) needs. Repo-authored
2026-09-23; R1 F21 (2026-10-16) added the run's event set, the incremental path and the override merge.
Needs the data disk mounted (config/paths.yaml ssd_root) for a scan; nothing here touches the
network — there is no API call in this file.

What it reads (all read-only):
  * <events-dir>/events_{econ,chemistry,math_stats}_cal2026-10.csv — the events: the star's OpenAlex
    author id, the school, the arrival year (econ star_id / arrival_year, chemistry and maths author_id /
    arrival_corrected). Default --events-dir = paths key `cal` (October: data/cal2026-10, 113/38/33).
  * <ssd_root>/derived/u2_person_map_11school_2026-07-16/person_map/data.parquet — economics only:
    the other OpenAlex author ids (fragments) that the U2 person map folds into an economics star's
    person, i.e. the same identity the economics frames use. The ids listed as `old_id` in the
    --id-corrections files (default data/cal2026-10/star_id_corrections_2026-10.csv) are known wrong
    ids and are never folded in.
  * <ssd_root>/snapshot/authors/**/part_*.gz — each author record's `affiliations`
    (institution + the years OpenAlex saw the author there).
  * <ssd_root>/snapshot/institutions/**/part_*.gz — display name, country, type, city, latitude,
    longitude of every institution that appears in those affiliations, plus the 11 destination
    universities (the SCHOOL_INST map the event pipeline pins).
  * <ssd_root>/derived/u1_full_11school_2026-07-16 and u1_edges_full_2026-07-05 — `works_affil`
    (work x author x institution) and `authorship_edges` (work x author x publication year): the
    number of works per author x institution x year, used by the map's tie-break rule.

What it writes (October's events: data/paper_inputs/star_origins_2026-10/ unless --out-dir; a run's
events: --out-dir, required, never that October folder):
  * star_author_ids.csv       field, star_id, author_id, role (star | u2_fragment)
  * affiliation_years.csv     author_id, institution_id, year, country_code_aff, n_works — one row
                              per author x institution x year with year <= the star's arrival year
                              (country_code_aff = the country OpenAlex prints inside the affiliation)
  * institutions.csv          institution_id, display_name, country_code, type, city, latitude,
                              longitude, in_snapshot
  * destinations.csv          school, institution_id
  * extract_report.json       counts, ids missing from the snapshot, partitions scanned, snapshot
                              manifest sha256, input sha256s (+ the reuse lists under --from-frozen)
  * human_origin_overrides.csv  a run's events only: the merged override table (below)
  * MANIFEST.sha256           the files above plus, when present, the hand-curated README.md and
                              human_origin_overrides.csv of the same folder (October: not written here).
                              Keys repo-relative inside the repo, else bare file names.
No personal names are written: author ids only.

R1 F21 — a run's event set (the M events of the J1a 'events' stage, October's column layout):
  --from-frozen DIR --frozen-events DIR   reuse a frozen extraction (October's): a star whose author-id
      set (star id + U2 fragments, role included) is unchanged and whose ids' year caps (largest arrival
      of the stars an id serves) are <= the frozen caps keeps the frozen affiliation rows of its ids,
      filtered to year <= the new cap; only new stars, changed id sets and raised caps are scanned.
      Reused rows must be a subset of the frozen rows (check_reused: AssertionError otherwise). The
      frozen files must match the frozen MANIFEST, the frozen events must be the ones the frozen
      extract_report names, and the snapshot manifests must equal the frozen ones. Institutions found
      in the frozen institutions.csv are reused; the rest are scanned.
  --stars FILE      optional filter: only these stars' events (one OpenAlex id per line; a header line
                    `star_id` is allowed). Not with October's folder as the output.
  Human overrides (the run's events only; flags required): --october-overrides (October's
  human_origin_overrides.csv), --r1-overrides (data/cal2026-10r1/inputs/star_origins/
  human_origin_overrides_r1.csv, not shipped), --events-decision (the run's events_decision_2026-10.json: its
  'redated' rows and 'id_corrected' map), --id-corrections. merge_overrides(): each October row is
  re-keyed through fig_star_origins.alias_event() to (discipline, star_id, arrival_year) of the run;
  a row whose event is not in the run is dropped and listed (e.g. a DROP star); a row whose event was
  re-dated needs an r1 confirmation row (carried_from = october:<discipline>:<star_id>:<old year>),
  since the origin is the last post before arrival and a moved year can move it; the r1 rows are
  appended. The merged table has October's columns plus carried_from and recheck.
  In a scan run an unconfirmed re-dated row is reported (--report: pending) and the merged table is
  NOT written, so the figure cannot run on it (its M pins need the file: fail closed). --overrides-only
  skips the scan and writes the merged table into an --out-dir that already holds the extraction
  (checked against the events); there an unconfirmed re-dated row is a STOP.
  --report FILE      name-free stage report (ids, codes, counts only): result, counts, reused/scanned
                     star ids, events whose machine origin is missing or ambiguous (works did not
                     decide the tie) and that have no human row, pending confirmations, dropped rows.

R1 U1 inputs (t-big-03, 2026-10-16). October's frozen n_works were counted on a local mirror of the
data disk that held only 120 of the 256 bucket files of the 11-school table's works_affil (an S3 sync
killed 2026-09-22: 116 empty bucket directories and 20 unfinished '*.parquet.<suffix>' downloads, which
the '**/*.parquet' glob silently skipped); every other U1 subtable it read was complete. The listing is
recorded in config/r1/star_origins_u1_view_2026-09-23.json. Before the count, u1_sources() now lists the
U1 files: a subtable with an unfinished download, an empty bucket directory or a bucket set unlike its
sibling's is STOP U1_PARTIAL. --u1-view FILE reads exactly the files a recorded view lists (sizes checked,
STOP U1_VIEW_MISMATCH); with the September view the October events reproduce the frozen extraction, and on
the complete tables only n_works moves, upward. extract_report.json records u1_inputs (and u1_view).
Rows reused under --from-frozen keep October's partial-table n_works, so J1a does not reuse: its
star_origins_extract row re-extracts every star on the complete tables (ruling 2026-10-16,
pipeline/NOT_REPRODUCIBLE.md entry 18); --from-frozen stays for reusing a complete-table extraction.

Run:  setup/.venv/bin/python tools/star_origins_extract_2026-10.py [--workers 12]          (October)
      "$PY" tools/star_origins_extract_2026-10.py --events-dir E --out-dir O --id-corrections C
           --events-decision J --october-overrides OO --r1-overrides R --report REP           (a run; J1a)
           [--from-frozen F --frozen-events FE]                     (reuse a complete-table extraction)
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import multiprocessing as mp
import pathlib
import re
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths  # noqa: E402

FIELDS = ("econ", "chemistry", "math_stats")
#: pinned copy of pipeline/stars/econ_fnfix_2026-08-15/code/00_make_u4_aug.py SCHOOL_INST
SCHOOL_INST = {"adelaide": "I5681781", "anu": "I118347636", "deakin": "I149704539",
               "macquarie": "I99043593", "melbourne": "I165779595", "monash": "I56590836",
               "sydney": "I129604602", "unsw": "I31746571", "uq": "I165143802",
               "uts": "I114017466", "uwa": "I177877127"}
U1_DIRS = ("u1_full_11school_2026-07-16", "u1_edges_full_2026-07-05")
#: the two U1 subtables the works count joins, read in every U1_DIRS table (u1_sources checks them)
U1_SUBTABLES = ("works_affil", "authorship_edges")
VIEW_SCHEMA = "sar.r1.star_origins_u1_view.v1"
VIEW_FILE = re.compile(r"^bucket=\d{3}/part-\d{5}\.parquet$")
PERSON_MAP = "u2_person_map_11school_2026-07-16/person_map/data.parquet"
OUT_DIR = REPO / "data" / "paper_inputs" / "star_origins_2026-10"
OCTOBER_CAL = REPO / "data" / "cal2026-10"
CORRECTIONS_NAME = "star_id_corrections_2026-10.csv"
PFX = b"https://openalex.org/"
OVERRIDES = "human_origin_overrides.csv"
OCT_COLS = ("discipline", "event_row", "star_id", "school", "arrival_year", "placement", "institution_id",
            "coords_from", "country_code", "human_evidence", "source_docs")
R1_COLS = OCT_COLS + ("carried_from", "recheck")
PLACEMENTS = ("human_institution", "machine_institution_same_country", "country_main_city")
EXTRACT = ("star_author_ids.csv", "affiliation_years.csv", "institutions.csv", "destinations.csv")
#: machine-origin tie-breaks that mean the works count did not decide (reported for an AI reading)
AMBIGUOUS_TIES = ("years", "id")


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def short(s: str | None) -> str:
    return s.rsplit("/", 1)[-1] if s else ""


def _f():
    """analysis/paper/fig_star_origins (alias_event, origin_of): imported only when a function needs it."""
    import analysis.paper.fig_star_origins as F
    return F


def event_table(events_dir: pathlib.Path, field: str) -> pathlib.Path:
    return pathlib.Path(events_dir) / f"events_{field}_cal2026-10.csv"


def load_events(events_dir: pathlib.Path | None = None) -> list[dict]:
    """The events of one event set (October's column layout): field, star_id, school, arrival, event_row."""
    events_dir = OCTOBER_CAL if events_dir is None else pathlib.Path(events_dir)
    out = []
    for f in FIELDS:
        with open(event_table(events_dir, f), newline="", encoding="utf-8") as fh:
            for k, r in enumerate(csv.DictReader(fh), 1):
                sid = r["star_id"] if f == "econ" else r["author_id"]
                yr = r["arrival_year"] if f == "econ" else r["arrival_corrected"]
                out.append({"field": f, "star_id": sid, "school": r["school"], "arrival": int(yr),
                            "event_row": k})
    return out


def _read_csv(p: pathlib.Path) -> tuple[list[str], list[dict]]:
    with open(p, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        return list(rd.fieldnames or []), list(rd)


def read_corrections(paths: list[pathlib.Path]) -> dict:
    """{old_id: new_id} from October-layout correction files (old_id,new_id,...); a conflict stops."""
    out: dict = {}
    for p in paths:
        _h, rows = _read_csv(p)
        for r in rows:
            if out.get(r["old_id"], r["new_id"]) != r["new_id"]:
                raise SystemExit(f"STOP CORRECTION_CONFLICT {r['old_id']}: {out[r['old_id']]} and {r['new_id']}")
            out[r["old_id"]] = r["new_id"]
    return out


def read_decision(p: pathlib.Path, corrections: dict) -> tuple[dict, dict]:
    """(redates {(star_id, old_year): new_year}, corrections + the decision's id_corrected)."""
    d = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    corr = dict(corrections)
    for old, new in (d.get("id_corrected") or {}).items():
        if corr.get(old, new) != new:
            raise SystemExit(f"STOP CORRECTION_CONFLICT {old}: {corr[old]} and {new}")
        corr[old] = new
    redates = {}
    for r in d.get("redated") or []:
        k = (r["star"], int(r["old_year"]))
        if redates.get(k, int(r["new_year"])) != int(r["new_year"]):
            raise SystemExit(f"STOP REDATE_CONFLICT {r['star']}:{r['old_year']}")
        redates[k] = int(r["new_year"])
    return redates, corr


# ---------------------------------------------------------------------------------------------------
# the incremental path (R1 F21 --from-frozen)
# ---------------------------------------------------------------------------------------------------
def id_sets(sa_rows) -> dict:
    """{star: {(author_id, role)}} from star_author_ids rows (field, star, author_id, role)."""
    out: dict = {}
    for _f_, s, aid, role in sa_rows:
        out.setdefault(s, set()).add((aid, role))
    return out


def caps(sa_rows, arrival_max: dict) -> dict:
    """{author_id: year cap} = the largest arrival year of the stars the id serves."""
    cap: dict = {}
    for _f_, s, aid, _role in sa_rows:
        cap[aid] = max(cap.get(aid, 0), arrival_max[s])
    return cap


def plan_reuse(new_sa: dict, new_cap: dict, frozen_sa: dict, frozen_cap: dict) -> dict:
    """Which stars keep their frozen rows: same id set and every id's cap <= its frozen cap. The others
    (new stars, changed id sets, raised caps) are scanned. An id of a scanned star is scanned even if a
    reused star shares it. Lists are sorted."""
    reuse, scan = [], []
    for s in sorted(new_sa):
        ids = new_sa[s]
        ok = s in frozen_sa and ids == frozen_sa[s] and all(
            aid in frozen_cap and new_cap[aid] <= frozen_cap[aid] for aid, _r in ids)
        (reuse if ok else scan).append(s)
    scan_ids = sorted({aid for s in scan for aid, _r in new_sa[s]})
    reuse_ids = sorted({aid for s in reuse for aid, _r in new_sa[s]} - set(scan_ids))
    return {"reuse_stars": reuse, "scan_stars": scan, "reuse_ids": reuse_ids, "scan_ids": scan_ids}


def reuse_rows(frozen: dict, reuse_ids, cap: dict) -> dict:
    """The frozen affiliation rows {(aid, iid, year): (country_code_aff, n_works)} of the reused ids,
    filtered to year <= the id's new cap."""
    ids = set(reuse_ids)
    return {k: v for k, v in frozen.items() if k[0] in ids and k[2] <= cap[k[0]]}


def check_reused(rows: dict, reuse_ids, frozen: dict) -> None:
    """Every row of a reused id must be a frozen row with the same values (AssertionError otherwise; an
    explicit raise, so python -O cannot drop it)."""
    ids = set(reuse_ids)
    bad = sorted(k for k, v in rows.items() if k[0] in ids and frozen.get(k) != v)
    if bad:
        raise AssertionError(f"reused rows not in the frozen extraction: {bad[:20]}")


def _manifest_shas(man: pathlib.Path) -> dict:
    """{basename: sha256} of a MANIFEST.sha256 ('<sha>  <key>' lines)."""
    out = {}
    for ln in man.read_text(encoding="utf-8").splitlines():
        if ln.strip():
            h, _, key = ln.partition("  ")
            out[pathlib.PurePosixPath(key.strip()).name] = h.strip()
    return out


def load_frozen(fz: pathlib.Path, fz_events: pathlib.Path) -> dict:
    """The frozen extraction, checked: its files against its MANIFEST, its events against the events its
    extract_report names (by basename)."""
    fz, fz_events = pathlib.Path(fz), pathlib.Path(fz_events)
    man = _manifest_shas(fz / "MANIFEST.sha256")
    for n in ("star_author_ids.csv", "affiliation_years.csv", "institutions.csv", "extract_report.json"):
        if man.get(n) != sha(fz / n):
            raise SystemExit(f"STOP FROZEN_PIN {fz / n}: not the file its MANIFEST pins")
    rep = json.loads((fz / "extract_report.json").read_text(encoding="utf-8"))
    named = {pathlib.PurePosixPath(k).name: h for k, h in rep["inputs_sha256"].items()}
    for f in FIELDS:
        p = event_table(fz_events, f)
        if named.get(p.name) != sha(p):
            raise SystemExit(f"STOP FROZEN_EVENTS {p}: not the event table the frozen extraction used")
    _h, sa = _read_csv(fz / "star_author_ids.csv")
    sa_rows = [(r["field"], r["star_id"], r["author_id"], r["role"]) for r in sa]
    arrival_max: dict = {}
    for e in load_events(fz_events):
        arrival_max[e["star_id"]] = max(arrival_max.get(e["star_id"], 0), e["arrival"])
    _h, aff = _read_csv(fz / "affiliation_years.csv")
    frozen_aff = {(r["author_id"], r["institution_id"], int(r["year"])): (r["country_code_aff"], r["n_works"])
                  for r in aff}
    _h, inst = _read_csv(fz / "institutions.csv")
    return {"sa": id_sets(sa_rows), "cap": caps(sa_rows, arrival_max), "aff": frozen_aff,
            "inst": {r["institution_id"]: r for r in inst}, "report": rep}


# ---------------------------------------------------------------------------------------------------
# the human override merge (R1 F21)
# ---------------------------------------------------------------------------------------------------
def _eid(star: str, year) -> str:
    return f"{star}:{int(year)}"


def merge_overrides(october: list[dict], r1: list[dict], events: list[dict], *, corrections: dict,
                    redates: dict, strict: bool) -> dict:
    """The run's override table: {'rows': [R1_COLS dicts, by field then event row], 'dropped': [October
    event ids not in the run], 'unconfirmed': [run event ids of re-dated October rows with no r1 row],
    'carried': n, 'r1': n}. strict=True: an unconfirmed row is a STOP. Every inconsistency is a STOP."""
    F = _f()
    ev_by = {(e["field"], e["star_id"], e["arrival"]): e for e in events}
    oct_keys = {f"october:{o['discipline']}:{o['star_id']}:{int(o['arrival_year'])}" for o in october}
    for r in r1:
        if not str(r.get("recheck") or "").strip():
            raise SystemExit(f"STOP OVERRIDE_R1_NO_RECHECK {_eid(r['star_id'], r['arrival_year'])}")
        if str(r.get("event_row") or "").strip():
            raise SystemExit(f"STOP OVERRIDE_R1_EVENT_ROW {_eid(r['star_id'], r['arrival_year'])}: leave event_row "
                             "empty (rows are keyed by star and year; the merge writes the run's row)")
        cf = str(r.get("carried_from") or "")
        if cf and cf not in oct_keys:
            raise SystemExit(f"STOP OVERRIDE_R1_CARRIED_FROM {cf}: no such October row")
    superseded = {r["carried_from"] for r in r1 if r.get("carried_from")}
    out, dropped, unconfirmed, n_carried = [], [], [], 0
    for o in october:
        ck = f"october:{o['discipline']}:{o['star_id']}:{int(o['arrival_year'])}"
        sid, yr = F.alias_event(o["star_id"], int(o["arrival_year"]), corrections=corrections, redates=redates)
        key = (o["discipline"], sid, yr)
        if key not in ev_by:
            dropped.append(_eid(o["star_id"], o["arrival_year"]))
            if ck in superseded:
                raise SystemExit(f"STOP OVERRIDE_R1_DROPPED_EVENT {ck}: its event is not in the run")
            continue
        if ck in superseded:
            continue                                  # the r1 row replaces it
        if yr != int(o["arrival_year"]):
            unconfirmed.append(_eid(sid, yr))
            continue
        e = ev_by[key]
        row = {c: o[c] for c in OCT_COLS}
        row.update(event_row=str(e["event_row"]), star_id=sid, arrival_year=str(yr), carried_from=ck, recheck="")
        out.append(row)
        n_carried += 1
    for r in r1:
        key = (r["discipline"], r["star_id"], int(r["arrival_year"]))
        if key not in ev_by:
            raise SystemExit(f"STOP OVERRIDE_R1_NO_EVENT {_eid(r['star_id'], r['arrival_year'])}")
        row = {c: str(r.get(c) or "") for c in R1_COLS}
        row["event_row"] = str(ev_by[key]["event_row"])
        out.append(row)
    seen = set()
    for row in out:
        key = (row["discipline"], row["star_id"], int(row["arrival_year"]))
        if key in seen:
            raise SystemExit(f"STOP OVERRIDE_DUPLICATE: duplicate rows for {_eid(key[1], key[2])}")
        seen.add(key)
        if row["school"] != ev_by[key]["school"]:
            raise SystemExit(f"STOP OVERRIDE_SCHOOL {_eid(key[1], key[2])}: the row's school is not the event's")
        if row["placement"] not in PLACEMENTS or not row["country_code"] or row["country_code"] == "AU":
            raise SystemExit(f"STOP OVERRIDE_ROW {_eid(key[1], key[2])}: placement / country")
    if unconfirmed and strict:
        raise SystemExit("STOP OVERRIDE_REDATE_UNCONFIRMED " + " ".join(unconfirmed) + ": a re-dated event's "
                         "October origin needs an r1 confirmation row (data/cal2026-10r1/inputs/star_origins, not shipped)")
    order = {f: i for i, f in enumerate(FIELDS)}
    out.sort(key=lambda r: (order[r["discipline"]], int(r["event_row"])))
    return {"rows": out, "dropped": sorted(dropped), "unconfirmed": sorted(unconfirmed), "carried": n_carried,
            "r1": len(r1)}


def read_overrides(p: pathlib.Path, cols: tuple) -> list[dict]:
    head, rows = _read_csv(p)
    if tuple(head) != cols:
        raise SystemExit(f"STOP OVERRIDE_COLUMNS {p}: want {list(cols)}")
    return rows


def write_overrides(out_dir: pathlib.Path, rows: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(R1_COLS)
    w.writerows([[r[c] for c in R1_COLS] for r in rows])
    (out_dir / OVERRIDES).write_text(buf.getvalue(), encoding="utf-8")


# ---------------------------------------------------------------------------------------------------
# the snapshot scan
# ---------------------------------------------------------------------------------------------------
def _scan_file(args):
    """Return {id: (updated_date, raw_json_line)} for the wanted ids found in one gz partition."""
    path, wanted, kind = args
    hits = {}
    date = pathlib.Path(path).parent.name.split("=", 1)[-1]
    with gzip.open(path, "rb") as fh:
        for line in fh:
            i = line.find(PFX, 0, 80)
            if i < 0:
                continue
            j = line.find(b'"', i)
            oid = line[i + len(PFX):j].decode("ascii", "replace")
            if oid in wanted:
                hits[oid] = (date, line.decode("utf-8"))
    return path, hits


def scan(root: pathlib.Path, wanted: set[str], kind: str, workers: int) -> tuple[dict, int, list]:
    if not wanted:
        return {}, 0, []
    files = sorted(root.glob("updated_date=*/part_*.gz"), key=lambda p: -p.stat().st_size)
    found: dict[str, tuple[str, str]] = {}
    dup: list[str] = []
    t0 = time.time()
    with mp.Pool(workers) as pool:
        for k, (path, hits) in enumerate(pool.imap_unordered(
                _scan_file, [(str(p), wanted, kind) for p in files]), 1):
            for oid, (date, line) in hits.items():
                if oid in found:
                    dup.append(oid)
                    if date <= found[oid][0]:
                        continue
                found[oid] = (date, line)
            if k % 100 == 0:
                print(f"  [{kind}] {k}/{len(files)} files, {len(found)} hits, {time.time()-t0:.0f}s",
                      flush=True)
    return found, len(files), sorted(set(dup))


# ---------------------------------------------------------------------------------------------------
# the U1 inputs of the works count (R1, t-big-03)
# ---------------------------------------------------------------------------------------------------
def check_view(view: dict) -> dict:
    """A recorded U1 view (--u1-view): {schema, tables: {u1 dir: {subtable: {files: {rel: bytes}}}}}."""
    if not isinstance(view, dict) or view.get("schema") != VIEW_SCHEMA or not isinstance(view.get("tables"), dict):
        raise SystemExit(f"--u1-view: not a {VIEW_SCHEMA} file")
    for d, subs in view["tables"].items():
        if d not in U1_DIRS or not isinstance(subs, dict) or not set(subs) <= set(U1_SUBTABLES):
            raise SystemExit(f"--u1-view: {d} {sorted(subs) if isinstance(subs, dict) else subs} is not a U1 "
                             f"subtable this tool reads ({U1_DIRS} x {U1_SUBTABLES})")
        for sub, body in subs.items():
            files = body.get("files") if isinstance(body, dict) else None
            if not isinstance(files, dict) or not all(
                    isinstance(r, str) and VIEW_FILE.match(r) and isinstance(n, int) and n > 0 for r, n in files.items()):
                raise SystemExit(f"--u1-view: {d}/{sub} files must map bucket=NNN/part-NNNNN.parquet to a byte count")
    return view


def u1_sources(derived: pathlib.Path, view: dict | None) -> tuple[dict, dict]:
    """The parquet files the works count reads, per (U1 dir, subtable), and their record (files, bytes).
    Without a view a subtable is every '*.parquet' under it (what the October glob read) and must be complete:
    no unfinished download (a '*.parquet.<suffix>' temp file), no empty bucket directory, and the same bucket
    set as the table's other subtable - else STOP U1_PARTIAL. October's 11-school works_affil failed all three
    (120 of 256 files on the 2026-09-23 mirror; config/r1/star_origins_u1_view_2026-09-23.json). With a view the
    listed files are read, each present with its recorded size, else STOP U1_VIEW_MISMATCH."""
    tables = check_view(view)["tables"] if view is not None else {}
    src, rec = {}, {}
    for d in U1_DIRS:
        buckets = {}
        for sub in U1_SUBTABLES:
            base = pathlib.Path(derived) / d / sub
            listed = (tables.get(d) or {}).get(sub)
            if listed is not None:
                files = [base / r for r in sorted(listed["files"])]
                bad = [r for r in sorted(listed["files"])
                       if not (base / r).is_file() or (base / r).stat().st_size != listed["files"][r]]
                if bad:
                    raise SystemExit(f"STOP U1_VIEW_MISMATCH {d}/{sub}: {len(bad)} listed file(s) absent or of "
                                     f"another size, e.g. {bad[:3]}")
                rec[f"{d}/{sub}"] = {"source": "view", "files": len(files), "bytes": sum(listed["files"].values())}
                src[(d, sub)] = files
                continue
            if not base.is_dir():
                raise SystemExit(f"STOP U1_PARTIAL {d}/{sub}: no such subtable under {derived}")
            files = sorted(p for p in base.rglob("*.parquet") if p.is_file())
            unfinished = sorted(p.relative_to(base).as_posix() for p in base.rglob("*.parquet.*") if p.is_file())
            dirs = sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith("bucket="))
            empty = [p.name for p in dirs if not any(p.rglob("*.parquet"))]
            if not files or unfinished or empty:
                raise SystemExit(f"STOP U1_PARTIAL {d}/{sub}: {len(files)} parquet file(s), {len(unfinished)} "
                                 f"unfinished download(s) {unfinished[:3]}, {len(empty)} empty bucket dir(s) {empty[:3]}")
            buckets[sub] = {p.name for p in dirs}
            rec[f"{d}/{sub}"] = {"source": "glob", "files": len(files), "bytes": sum(p.stat().st_size for p in files),
                                 "bucket_dirs": len(dirs)}
            src[(d, sub)] = files
        if len(buckets) == len(U1_SUBTABLES) and len({frozenset(b) for b in buckets.values()}) != 1:
            raise SystemExit(f"STOP U1_PARTIAL {d}: bucket sets differ between subtables "
                             + ", ".join(f"{s} {len(b)}" for s, b in buckets.items()))
    return src, rec


def _parquet_list(files) -> str:
    return "[" + ", ".join("'" + str(p).replace("'", "''") + "'" for p in files) + "]"


# ---------------------------------------------------------------------------------------------------
# helpers for main
# ---------------------------------------------------------------------------------------------------
def _same(a: pathlib.Path, b: pathlib.Path) -> bool:
    return pathlib.Path(a).resolve() == pathlib.Path(b).resolve()


def _inside(p: pathlib.Path, root: pathlib.Path) -> bool:
    p, root = pathlib.Path(p).resolve(), pathlib.Path(root).resolve()
    return p == root or root in p.parents


def _key(p: pathlib.Path) -> str:
    """A path as a report / MANIFEST key: repo-relative inside the repo (October's form), else absolute."""
    try:
        return str(pathlib.Path(p).resolve().relative_to(REPO.resolve()))
    except ValueError:
        return str(pathlib.Path(p).resolve())


def write_manifest(out_dir: pathlib.Path, names: list[str]) -> None:
    """MANIFEST.sha256 of out_dir: keys repo-relative when out_dir is inside the repo, else bare names."""
    inside = _inside(out_dir, REPO)
    names = sorted(set(names) | {n for n in ("README.md", OVERRIDES) if (out_dir / n).is_file()})
    (out_dir / "MANIFEST.sha256").write_text(
        "".join(f"{sha(out_dir / n)}  {_key(out_dir / n) if inside else n}\n" for n in names), encoding="utf-8")


def _read_stars(p: pathlib.Path) -> set[str]:
    ids = {ln.strip() for ln in pathlib.Path(p).read_text(encoding="utf-8").splitlines() if ln.strip()}
    return ids - {"star_id"}


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--events-dir", type=pathlib.Path, help="event tables (default: paths key cal)")
    ap.add_argument("--out-dir", type=pathlib.Path, help="required unless the events are October's")
    ap.add_argument("--from-frozen", type=pathlib.Path, help="a frozen extraction to reuse (October's)")
    ap.add_argument("--frozen-events", type=pathlib.Path, help="the event tables of the frozen extraction")
    ap.add_argument("--stars", type=pathlib.Path, help="only these stars' events (one id per line)")
    ap.add_argument("--id-corrections", type=pathlib.Path, action="append",
                    help="old_id,new_id files (repeatable; default: <cal>/star_id_corrections_2026-10.csv)")
    ap.add_argument("--events-decision", type=pathlib.Path, help="the run's events_decision_2026-10.json")
    ap.add_argument("--october-overrides", type=pathlib.Path, help="October's human_origin_overrides.csv")
    ap.add_argument("--r1-overrides", type=pathlib.Path, help="human_origin_overrides_r1.csv")
    ap.add_argument("--overrides-only", action="store_true", help="merge the overrides into --out-dir; no scan")
    ap.add_argument("--report", type=pathlib.Path, help="name-free stage report (JSON)")
    ap.add_argument("--u1-view", type=pathlib.Path,
                    help="read exactly the U1 files a recorded view lists (sar.r1.star_origins_u1_view.v1)")
    return ap.parse_args(argv)


def check_args(a, P) -> tuple[pathlib.Path, pathlib.Path, bool]:
    """(events_dir, out_dir, october) after the CLI rules; every refusal is a SystemExit naming its flag."""
    events_dir = pathlib.Path(a.events_dir) if a.events_dir else pathlib.Path(P["cal"])
    october = _same(events_dir, OCTOBER_CAL)
    merge_flags = [n for n, v in (("--r1-overrides", a.r1_overrides), ("--october-overrides", a.october_overrides),
                                  ("--events-decision", a.events_decision), ("--overrides-only", a.overrides_only))
                   if v]
    if october:
        if merge_flags:
            raise SystemExit(f"{' '.join(merge_flags)}: October's events keep October's hand-curated override "
                             "table; the merge is for a run's events only")
        out_dir = pathlib.Path(a.out_dir) if a.out_dir else OUT_DIR
    else:
        if not a.out_dir:
            raise SystemExit(f"--out-dir is required for a run's events ({events_dir} is not October's)")
        out_dir = pathlib.Path(a.out_dir)
        if _inside(out_dir, OUT_DIR):
            raise SystemExit(f"--out-dir {out_dir}: data/paper_inputs/star_origins_2026-10 holds October's "
                             "frozen extraction and takes only October's events")
        missing = [n for n, v in (("--october-overrides", a.october_overrides), ("--r1-overrides", a.r1_overrides),
                                  ("--events-decision", a.events_decision)) if not v]
        if missing:
            raise SystemExit(f"{' '.join(missing)} required for a run's events (the human override merge)")
    if a.from_frozen and not a.frozen_events:
        raise SystemExit("--from-frozen needs --frozen-events (the event tables the frozen extraction used)")
    if a.from_frozen and _inside(out_dir, a.from_frozen):
        raise SystemExit(f"--out-dir {out_dir} lies in --from-frozen {a.from_frozen}")
    if a.stars and _inside(out_dir, OUT_DIR):
        raise SystemExit("--stars: a filtered extraction may not replace October's frozen folder")
    if a.overrides_only and (a.from_frozen or a.stars):
        raise SystemExit("--overrides-only scans nothing: no --from-frozen / --stars")
    return events_dir, out_dir, october


def _overrides(a, events, corrections_files):
    corr = read_corrections(corrections_files)
    redates, corr = read_decision(a.events_decision, corr)
    october = read_overrides(a.october_overrides, OCT_COLS)
    r1 = read_overrides(a.r1_overrides, R1_COLS)
    return october, r1, corr, redates


def _write_report(path, report: dict) -> None:
    if path:
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(path).write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def overrides_only(a, events_dir, out_dir, events, corrections_files) -> None:
    """Merge the overrides into an existing extraction (strict: an unconfirmed re-dated row stops)."""
    rep = json.loads((out_dir / "extract_report.json").read_text(encoding="utf-8"))
    named = {pathlib.PurePosixPath(k).name: h for k, h in rep["inputs_sha256"].items()}
    for f in FIELDS:
        p = event_table(events_dir, f)
        if named.get(p.name) != sha(p):
            raise SystemExit(f"STOP EXTRACT_EVENTS {p}: the extraction in {out_dir} was made from other events")
    october, r1, corr, redates = _overrides(a, events, corrections_files)
    m = merge_overrides(october, r1, events, corrections=corr, redates=redates, strict=True)
    write_overrides(out_dir, m["rows"])
    write_manifest(out_dir, [n for n in EXTRACT + ("extract_report.json",) if (out_dir / n).is_file()])
    _write_report(a.report, {"result": "OK", "mode": "overrides_only",
                             "counts": {"n_rows": len(m["rows"]), "n_carried": m["carried"], "n_r1": m["r1"],
                                        "n_dropped": len(m["dropped"])},
                             "dropped": {"ids": m["dropped"]}})
    print(f"overrides: {len(m['rows'])} rows ({m['carried']} carried, {m['r1']} r1), dropped {m['dropped']} "
          f"-> {out_dir / OVERRIDES}", flush=True)


def review_ids(events, sa_rows, aff_rows, counts_of, inst_rows, covered) -> dict:
    """Events with no human row whose machine origin (fig_star_origins' rule) is missing or ambiguous."""
    F = _f()
    ids: dict = {}
    for f, s, aid, role in sa_rows:
        ids.setdefault(s, {"star": [], "u2_fragment": []})[role].append(aid)
    aff: dict = {}
    for (aid, iid, y), (cc, n) in sorted(aff_rows.items()):
        aff.setdefault(aid, []).append((iid, y, cc, int(counts_of((aid, iid, y), n))))
    inst = {r[0]: {"country_code": r[2]} for r in inst_rows}
    missing, ambiguous = [], []
    for e in events:
        if (e["field"], e["star_id"], e["arrival"]) in covered:
            continue
        inp = {"ids": {e["star_id"]: ids.get(e["star_id"], {"star": [], "u2_fragment": []})}, "aff": aff,
               "inst": inst}
        o, _src, _used = F.machine_origin({"field": e["field"], "star": e["star_id"], "arrival": e["arrival"]}, inp)
        if o is None:
            missing.append(_eid(e["star_id"], e["arrival"]))
        elif o["tie_break"] in AMBIGUOUS_TIES:
            ambiguous.append(_eid(e["star_id"], e["arrival"]))
    return {"missing": sorted(missing), "ambiguous": sorted(ambiguous)}


# ---------------------------------------------------------------------------------------------------
def main(argv=None) -> None:
    a = parse_args(argv)
    P = load_paths()
    events_dir, out_dir, october = check_args(a, P)
    corrections_files = a.id_corrections or [pathlib.Path(P["cal"]) / CORRECTIONS_NAME]
    events = load_events(events_dir)
    if a.stars:
        keep = _read_stars(a.stars)
        events = [e for e in events if e["star_id"] in keep]
    if a.overrides_only:
        return overrides_only(a, events_dir, out_dir, events, corrections_files)

    ssd = pathlib.Path(P["ssd_root"])
    snap, derived = ssd / "snapshot", ssd / "derived"
    t0 = time.time()
    arrival_max: dict[str, int] = {}
    field_of: dict[str, str] = {}
    for e in events:
        arrival_max[e["star_id"]] = max(arrival_max.get(e["star_id"], 0), e["arrival"])
        field_of[e["star_id"]] = e["field"]

    # --- econ: the U2 person map's other fragments of each star's person (known-wrong ids excluded)
    wrong_ids = set(read_corrections(corrections_files))
    import duckdb
    con = duckdb.connect()
    con.execute("PRAGMA threads=12")
    econ_ids = sorted(s for s, f in field_of.items() if f == "econ")
    con.execute("CREATE TABLE s (a VARCHAR)")
    con.executemany("INSERT INTO s VALUES (?)", [(x,) for x in econ_ids])
    pm = derived / PERSON_MAP
    frag_rows = con.execute(f"""
        WITH p AS (SELECT m.person_id, s.a FROM read_parquet('{pm}') m JOIN s ON m.author_id = s.a)
        SELECT p.a AS star_id, m.author_id FROM p JOIN read_parquet('{pm}') m ON m.person_id = p.person_id
        WHERE m.author_id <> p.a ORDER BY 1, 2""").fetchall()
    sa_rows = [(field_of[s], s, s, "star") for s in sorted(field_of)]
    n_wrong_skipped = 0
    for s, aid in frag_rows:
        if aid in wrong_ids:
            n_wrong_skipped += 1
            continue
        sa_rows.append(("econ", s, aid, "u2_fragment"))
    sa_rows.sort(key=lambda r: (r[0], r[1], r[3] != "star", r[2]))
    # an author id may serve more than one star only in principle; year cap = the largest arrival
    cap = caps(sa_rows, arrival_max)
    wanted_a = set(cap)

    # --- what to scan: everything, or (--from-frozen) only new stars / changed id sets / raised caps
    frozen = None
    if a.from_frozen:
        frozen = load_frozen(a.from_frozen, a.frozen_events)
        plan = plan_reuse(id_sets(sa_rows), cap, frozen["sa"], frozen["cap"])
        if plan["reuse_ids"]:
            for k in ("authors", "institutions"):
                m = snap / k / "manifest.json"
                if not m.is_file() or sha(m) != frozen["report"]["snapshot_manifest_sha256"][k]:
                    raise SystemExit(f"STOP SNAPSHOT_CHANGED {m}: not the snapshot the frozen extraction read")
    else:
        plan = {"reuse_stars": [], "scan_stars": sorted(field_of), "reuse_ids": [], "scan_ids": sorted(wanted_a)}
    scan_a = set(plan["scan_ids"])
    print(f"stars {len(field_of)}, author ids {len(wanted_a)} (fragments {len(sa_rows) - len(field_of)}, "
          f"wrong ids skipped {n_wrong_skipped}); scan {len(scan_a)} ids of {len(plan['scan_stars'])} stars, "
          f"reuse {len(plan['reuse_ids'])} ids of {len(plan['reuse_stars'])} stars", flush=True)
    if scan_a and not (snap / "authors").is_dir():
        raise SystemExit(f"data disk not mounted: {snap}")

    # --- snapshot authors -------------------------------------------------------------------------
    found_a, n_files_a, dup_a = scan(snap / "authors", scan_a, "authors", a.workers)
    aff_rows: dict[tuple[str, str, int], str] = {}
    for aid, (_d, line) in found_a.items():
        rec = json.loads(line)
        for af in rec.get("affiliations") or []:
            inst = af.get("institution") or {}
            iid = short(inst.get("id"))
            if not iid:
                continue
            for y in af.get("years") or []:
                if y is not None and int(y) <= cap[aid]:
                    aff_rows[(aid, iid, int(y))] = inst.get("country_code") or ""
    missing_a = sorted(scan_a - set(found_a))
    print(f"authors found {len(found_a)}/{len(scan_a)}, missing {missing_a}, "
          f"affiliation-year rows {len(aff_rows)}, {time.time()-t0:.0f}s", flush=True)

    # --- works per author x institution x year (U1 extractions, union of distinct work rows) -------
    counts: dict = {}
    u1_rec: dict = {}
    if scan_a:
        # R1 (t-big-03): list the U1 files first - a partial subtable is a STOP, a recorded view is read exactly
        view = json.loads(a.u1_view.read_text(encoding="utf-8")) if a.u1_view else None
        u1_src, u1_rec = u1_sources(derived, view)
        con.execute("CREATE TABLE w (a VARCHAR)")
        con.executemany("INSERT INTO w VALUES (?)", [(x,) for x in sorted(scan_a)])
        parts = []
        for d in U1_DIRS:
            parts.append(f"""SELECT wa.work_id, wa.author_id, wa.institution_id, e.publication_year AS year
                FROM read_parquet({_parquet_list(u1_src[(d, "works_affil")])}, hive_partitioning=0) wa
                JOIN w ON wa.author_id = w.a
                JOIN read_parquet({_parquet_list(u1_src[(d, "authorship_edges")])}, hive_partitioning=0) e
                  ON e.work_id = wa.work_id AND e.author_id = wa.author_id""")
        con.execute("CREATE TABLE wk AS SELECT DISTINCT * FROM (" + " UNION ALL ".join(parts) + ")")
        counts = {(r[0], r[1], int(r[2])): int(r[3]) for r in con.execute(
            "SELECT author_id, institution_id, year, count(DISTINCT work_id) FROM wk "
            "WHERE institution_id IS NOT NULL AND year IS NOT NULL GROUP BY 1, 2, 3").fetchall()}

    # all rows: (cc, n_works); scanned rows take the U1 counts, reused rows keep the frozen values
    all_rows: dict = {k: (cc, counts.get(k, 0)) for k, cc in aff_rows.items()}
    if frozen is not None:
        reused = reuse_rows(frozen["aff"], plan["reuse_ids"], cap)
        check_reused(reused, plan["reuse_ids"], frozen["aff"])
        all_rows.update(reused)

    # --- snapshot institutions ---------------------------------------------------------------------
    wanted_i = {k[1] for k in all_rows} | set(SCHOOL_INST.values())
    reuse_i = {i: r for i, r in (frozen["inst"] if frozen else {}).items()
               if i in wanted_i and r["in_snapshot"] == "1"}
    scan_i = wanted_i - set(reuse_i)
    if scan_i and not (snap / "institutions").is_dir():
        raise SystemExit(f"data disk not mounted: {snap}")
    found_i, n_files_i, dup_i = scan(snap / "institutions", scan_i, "institutions", a.workers)
    inst_rows = []
    cc_from_aff: dict[str, str] = {}
    for (aid, iid, y), (cc, _n) in sorted(all_rows.items()):
        if cc and iid not in cc_from_aff:
            cc_from_aff[iid] = cc
    for iid in sorted(wanted_i):
        if iid in reuse_i:
            r = reuse_i[iid]
            inst_rows.append((iid, r["display_name"], r["country_code"], r["type"], r["city"], r["latitude"],
                              r["longitude"], "1"))
        elif iid in found_i:
            rec = json.loads(found_i[iid][1])
            geo = rec.get("geo") or {}
            inst_rows.append((iid, rec.get("display_name") or "", rec.get("country_code") or "",
                              rec.get("type") or "", geo.get("city") or "",
                              "" if geo.get("latitude") is None else repr(float(geo["latitude"])),
                              "" if geo.get("longitude") is None else repr(float(geo["longitude"])),
                              "1"))
        else:
            inst_rows.append((iid, "", cc_from_aff.get(iid, ""), "", "", "", "", "0"))
    missing_i = sorted(scan_i - set(found_i))

    # --- human overrides (a run's events only) --------------------------------------------------------
    merged = None
    covered: set = set()
    if not october:
        oct_rows, r1_rows, corr, redates = _overrides(a, events, corrections_files)
        merged = merge_overrides(oct_rows, r1_rows, events, corrections=corr, redates=redates, strict=False)
        covered = {(r["discipline"], r["star_id"], int(r["arrival_year"])) for r in merged["rows"]}
        covered |= {(e["field"], e["star_id"], e["arrival"]) for e in events
                    if _eid(e["star_id"], e["arrival"]) in set(merged["unconfirmed"])}

    # --- write --------------------------------------------------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)

    def wcsv(name, header, rows):
        with open(out_dir / name, "w", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh, lineterminator="\n")
            wr.writerow(header)
            wr.writerows(rows)

    wcsv("star_author_ids.csv", ["field", "star_id", "author_id", "role"], sa_rows)
    wcsv("affiliation_years.csv", ["author_id", "institution_id", "year", "country_code_aff", "n_works"],
         [(aid, iid, y, cc, n) for (aid, iid, y), (cc, n) in sorted(all_rows.items())])
    wcsv("institutions.csv", ["institution_id", "display_name", "country_code", "type", "city",
                              "latitude", "longitude", "in_snapshot"], inst_rows)
    wcsv("destinations.csv", ["school", "institution_id"], sorted(SCHOOL_INST.items()))
    inputs = {_key(p): sha(p) for p in [event_table(events_dir, f) for f in FIELDS] + list(corrections_files)}
    snap_man = snap / "manifest.json"
    report = {
        "_about": "tools/star_origins_extract_2026-10.py — offline snapshot extraction for the star-origins map",
        "snapshot_manifest_sha256": {k: (sha(snap / k / "manifest.json") if (snap / k / "manifest.json").is_file()
                                         else None) for k in ("authors", "institutions")},
        "snapshot_manifest_date": json.loads(snap_man.read_text())["date"] if snap_man.is_file() else None,
        "person_map": str(PERSON_MAP), "person_map_sha256": sha(pm),
        "u1_dirs": list(U1_DIRS),
        "u1_inputs": u1_rec,
        "inputs_sha256": inputs,
        "n_stars": len(field_of), "n_author_ids": len(wanted_a),
        "n_u2_fragments": len(sa_rows) - len(field_of), "n_wrong_ids_skipped": n_wrong_skipped,
        "authors_files_scanned": n_files_a, "authors_found": len(found_a),
        "authors_missing": missing_a, "authors_duplicate_records": dup_a,
        "institutions_files_scanned": n_files_i, "institutions_wanted": len(wanted_i),
        "institutions_missing": missing_i, "institutions_duplicate_records": dup_i,
        "affiliation_year_rows": len(all_rows), "work_count_cells": len(counts),
        "network_requests": 0,
    }
    if frozen is not None:
        report.update({"from_frozen": _key(a.from_frozen), "frozen_events": _key(a.frozen_events),
                       "reused_stars": plan["reuse_stars"], "scanned_stars": plan["scan_stars"],
                       "reused_author_ids": len(plan["reuse_ids"]), "scanned_author_ids": len(plan["scan_ids"]),
                       "reused_institutions": len(reuse_i), "scanned_institutions": len(scan_i)})
    if a.u1_view:
        report["u1_view"] = {"file": _key(a.u1_view), "sha256": sha(a.u1_view)}
    if not october:
        report["events_dir"] = _key(events_dir)
    (out_dir / "extract_report.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                                                 encoding="utf-8")
    pending = merged is not None and bool(merged["unconfirmed"])
    if merged is not None and not pending:
        write_overrides(out_dir, merged["rows"])
    names = ["affiliation_years.csv", "destinations.csv", "extract_report.json", "institutions.csv",
             "star_author_ids.csv"]
    # hand-curated files that live in the same folder stay in the manifest (2026-09-23 map revision)
    write_manifest(out_dir, names)

    rev = review_ids(events, sa_rows, all_rows, lambda k, n: n, inst_rows, covered)
    out = {"result": "PENDING" if pending else "OK", "mode": "october" if october else "run",
           "counts": {"n_events": len(events), "n_stars": len(field_of), "n_author_ids": len(wanted_a),
                      "n_authors_scanned": len(scan_a), "n_authors_reused": len(plan["reuse_ids"]),
                      "n_institutions_scanned": len(scan_i), "n_institutions_reused": len(reuse_i),
                      "n_missing_origin": len(rev["missing"]), "n_ambiguous_origin": len(rev["ambiguous"])},
           "reused": {"ids": plan["reuse_stars"]}, "scanned": {"ids": plan["scan_stars"]},
           "missing": {"ids": rev["missing"]}, "ambiguous": {"ids": rev["ambiguous"]}}
    if merged is not None:
        out["counts"].update(n_override_rows=len(merged["rows"]), n_override_carried=merged["carried"],
                             n_override_r1=merged["r1"], n_override_dropped=len(merged["dropped"]),
                             n_override_pending=len(merged["unconfirmed"]))
        out["pending"] = {"ids": merged["unconfirmed"]}
        out["dropped"] = {"ids": merged["dropped"]}
    _write_report(a.report, out)
    print(f"done in {time.time()-t0:.0f}s -> {_key(out_dir)}"
          + (f"; overrides PENDING {merged['unconfirmed']} (merged table not written)" if pending else ""),
          flush=True)


if __name__ == "__main__":
    main()
