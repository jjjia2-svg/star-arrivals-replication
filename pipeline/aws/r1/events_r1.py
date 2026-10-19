#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 F10 (+ N16-S14): the event tables and top-5% subsets of one run, in October's basenames (EC2 only).

  --mode b0  --repo R --rank-tables DIR(kind B0) --raw-0828 DIR --corrections F --october DIR --out DIR
      October's six tables and events_decision_2026-10.json, rebuilt through verdict_source (B0 = October's
      write_events.py semantics) and written only if every byte equals the October file (else STOP).
  --mode m   ... the b0 flags (rank tables kind M) + --flips F --add-list F --addlist-summary F --fixes F
             --overrides F --calls DIR --arrival-checks DIR
      October's lines rebuilt from the 08-28 tables through verdict_source.filter_october_rows (the signed
      verdicts): the DROP stars' events leave, every other October line stays byte for byte in October order;
      signed redates (fixes_1001 'redate', person_overrides 'arrival_year' for October KEEP stars) change only
      the event id and arrival columns of their one line; A5110738002's 08-28 line (KEEP, dropped in October) comes
      back byte for byte after the October lines; then the add-list ACCEPT rows in file order. Top-5% subsets
      follow verdict_source's p05 (decision 4 lives in restake_r1). Also writes counts.json (sar.r1.counts.v1),
      star_aliases_r1.csv (from the calls stage's rank_adds.json), summary.json (ids and counts) and RESULT.txt.

Every contradiction is a STOP (SystemExit 'STOP <CODE> <ids>'; summary.json result STOP; no table written).
October files are only read; outputs go to --out. Readers of October's basenames run unedited on --out.
"""
from __future__ import annotations

import argparse
import csv
import importlib
import importlib.util
import io
import json
import os
import pathlib
import sys

AWS_HOSTS = ("ec2-r1-test", "ec2-r1")
FIELDS = ("econ", "chemistry", "math_stats")
ID_COL = {"econ": 1, "chemistry": 2, "math_stats": 2}
ARR_COL = {"econ": 3, "chemistry": 4, "math_stats": 4}
DECISION = "events_decision_2026-10.json"
SIGNED_ADD = "signed_add_list_r1_2026-10-12"
ADD_LIST_REPO_PATH = "data/cal2026-10r1/inputs/add_list_r1.json"   # signed R1 input (not shipped)
ECON_NEW_COLS = ("event_id", "star_id", "school", "arrival_year", "arrival_source", "arrival_evidence", "reason",
                 "evidence_source")
CM_COLS = ["field", "school", "author_id", "display_name", "arrival_corrected", "evidence_grade", "evidence_url",
           "signature"]
FIX_KINDS = {"redate", "drop", "merge_ids", "clean_rerank", "p05_out", "below_cut_1001"}
OVERRIDE_ACTIONS = {"status", "merge_ids", "arrival_year"}
CHECK_SCHEMA = "sar.r1.arrival_check.v1"
COUNTS_SCHEMA = "sar.r1.counts.v1"
DECISION_SCHEMA = "sar.r1.events_decision.v1"
ALIAS_SOURCE = "calls:rank_adds.json"
M_ONLY = ("flips", "add_list", "addlist_summary", "fixes", "overrides", "calls", "arrival_checks")


class Stop(Exception):
    """A contradiction between the inputs: the stage stops and the author or the rank chain decides."""


def table_name(field: str, p05: bool = False) -> str:
    return f"events_{field}_cal2026-10{'_p05' if p05 else ''}.csv"


# ------------------------------------------------------------------------------------------------ small helpers
def _parse(ln: str) -> list:
    return next(csv.reader([ln]))


def _join(fields) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="").writerow(fields)
    return buf.getvalue()


def _key(field: str, f: list) -> str:
    return f[0] if field == "econ" else f"{f[2]}:{f[1]}"


def _star(field: str, ln: str) -> str:
    return _parse(ln)[ID_COL[field]]


def _lines(p) -> list:
    return [ln for ln in pathlib.Path(p).read_bytes().decode("utf-8").split("\n") if ln]


def _text(lines) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def _read_csv(p) -> list:
    with open(p, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _json(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def _year(v, where: str) -> int:
    try:
        y = int(str(v).strip())
    except ValueError:
        raise Stop(f"BAD_YEAR {where}: {v!r}") from None
    if str(y) != str(v).strip():
        raise Stop(f"BAD_YEAR {where}: {v!r}")
    return y


def _verdict_source(repo):
    for d in (pathlib.Path(repo) / "pipeline" / "aws" / "r1", pathlib.Path(__file__).resolve().parent):
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
    return importlib.import_module("verdict_source")


def _in_window(repo):
    """caliber_2026-08-28.in_window: the signed 1999-2024 event window, never retyped here."""
    p = pathlib.Path(repo) / "pipeline" / "stars" / "caliber_2026-08-28" / "caliber.py"
    spec = importlib.util.spec_from_file_location("_events_r1_caliber", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                                        # type: ignore[union-attr]
    return mod.in_window


# ------------------------------------------------------------------------------------------------ redates
def signed_redates(fixes: list, overrides: list) -> list:
    """fixes_1001 'redate' + person_overrides 'arrival_year' rows -> [{star, year, source}] (one per person;
    the same year twice is one redate, two years is a STOP)."""
    out: dict = {}
    rows = [(r["author_id"], r["value"], "fixes_1001 redate") for r in fixes if r.get("fix") == "redate"]
    rows += [(r["author_id"], r["value"], "person_overrides arrival_year")
             for r in overrides if r.get("action") == "arrival_year"]
    for pid, val, src in rows:
        y = _year(val, f"{src} {pid}")
        if pid in out and out[pid]["year"] != y:
            raise Stop(f"REDATE_TWO_YEARS {pid}: {out[pid]['year']} ({out[pid]['source']}) and {y} ({src})")
        if pid in out:
            out[pid]["source"] += f" + {src}"
        else:
            out[pid] = {"star": pid, "year": y, "source": src}
    return list(out.values())


def _hits(tables: dict, star: str) -> list:
    return [(f, i) for f in FIELDS for i, ln in enumerate(tables.get(f, [])[1:], 1) if _star(f, ln) == star]


def _rewrite(line: str, changes: dict) -> str:
    """Change the given columns of one csv line in place; every byte after the last changed column stays."""
    f = _parse(line)
    n = max(changes) + 1
    head = _join(f[:n])
    if n >= len(f) or not line.startswith(head + ","):
        raise Stop(f"REDATE_NOT_IN_PLACE {f[:3]}: the line cannot be rewritten without touching later bytes")
    g = list(f[:n])
    for c, v in changes.items():
        g[c] = v
    new = _join(g) + line[len(head):]
    want = list(f)
    for c, v in changes.items():
        want[c] = v
    if _parse(new) != want:
        raise Stop(f"REDATE_NOT_IN_PLACE {f[:3]}")
    return new


def apply_redates(tables: dict, plan: list):
    """Re-date each planned star's one event line (econ: event id col 0 and arrival col 3; chemistry/maths:
    arrival_corrected col 4). A plan row that hits no line or two lines is a STOP. Returns (tables, records)."""
    tables = {f: list(v) for f, v in tables.items()}
    records = []
    for p in plan:
        star, year = p["star"], int(p["year"])
        hits = _hits(tables, star)
        if len(hits) != 1:
            raise Stop(f"REDATE_HITS {star} ({p['source']}): {len(hits)} event lines, want exactly one")
        field, i = hits[0]
        f = _parse(tables[field][i])
        old = f[ARR_COL[field]]
        changes = {ARR_COL[field]: str(year)}
        if field == "econ":
            if f[0] != f"{star}:{old}":
                raise Stop(f"REDATE_EVENT_ID {star}: event id {f[0]} does not carry its arrival {old}")
            changes[0] = f"{star}:{year}"
        new = _rewrite(tables[field][i], changes)
        tables[field][i] = new
        records.append({"field": field, "star": star, "old_event": _key(field, f), "new_event": _key(field, _parse(new)),
                        "old_year": int(old), "new_year": year, "source": p["source"]})
    return tables, records


def redates_from_inputs(fixes: list, overrides: list, october_events: dict) -> dict:
    """{old_event: new_event} for the signed redates that name a star with an event in october_events
    ({field: [header, lines...]}); econ ids change with the year, chemistry/maths ids (author:school) do not."""
    plan = [p for p in signed_redates(fixes, overrides) if _hits(october_events, p["star"])]
    return {r["old_event"]: r["new_event"] for r in apply_redates(october_events, plan)[1]}


# ------------------------------------------------------------------------------------------------ signed lists
def load_signed(flips_path, add_path) -> dict:
    fl, ad = _json(flips_path), _json(add_path)
    if fl.get("schema") != "sar.r1.flips.v1" or ad.get("schema") != "sar.r1.add_list.v1":
        raise Stop("BAD_SCHEMA flips_r1.json / add_list_r1.json")
    flips, adds = fl["rows"], ad["rows"]
    undecided = [r.get("person_id") for r in flips + adds if not str(r.get("decided") or "").strip()]
    if undecided:
        raise Stop(f"UNDECIDED_ROW {' '.join(map(str, undecided[:50]))}")
    bad = [r["person_id"] for r in flips if r.get("verdict") not in ("KEEP", "DROP") or r.get("field") not in FIELDS]
    bad += [r["person_id"] for r in adds if r.get("verdict") not in ("ACCEPT", "REJECT")
            or (r.get("verdict") == "ACCEPT" and r.get("field") not in FIELDS)]
    if bad:
        raise Stop(f"BAD_VERDICT_ROW {' '.join(bad[:50])}")
    by_id = {}
    for r in flips:
        if r["person_id"] in by_id:
            raise Stop(f"DUPLICATE_FLIPS_ROW {r['person_id']}")
        by_id[r["person_id"]] = r
    add_ids = {}
    for r in adds:
        for i in [r["person_id"]] + [x for x in str(r.get("all_ids") or "").split("|") if x]:
            if i in add_ids and add_ids[i] is not r:
                raise Stop(f"DUPLICATE_ADD_LIST_ID {i}")
            add_ids[i] = r
    both = sorted(set(by_id) & set(add_ids))
    if both:
        raise Stop(f"IN_BOTH_LISTS {' '.join(both)}")
    accept = [r for r in adds if r["verdict"] == "ACCEPT"]
    return {"flips": by_id, "accept": accept, "add_by_id": add_ids, "n_flips": len(flips)}


# ------------------------------------------------------------------------------------------------ arrival checks
def check_arrival_checks(check_dir, october: dict, plan_by_star: dict, in_window) -> list:
    """N16-S14: each sar.r1.arrival_check.v1 file names an October event; agreed and decided; a verified year
    inside the window must be met by exactly that redate row (none when it equals the claimed year); a year
    outside the window STOPs for the author; no verified year = keep the claimed one (reported)."""
    records = []
    for p in sorted(pathlib.Path(check_dir).glob("*.json")):
        d = _json(p)
        pid = d.get("person_id")
        if d.get("schema") != CHECK_SCHEMA or not pid or p.stem != pid:
            raise Stop(f"BAD_ARRIVAL_CHECK {p.name}: schema {CHECK_SCHEMA} and person_id = file name")
        if d.get("agree") is not True or not str(d.get("decided") or "").strip() or not d.get("second_checker"):
            raise Stop(f"ARRIVAL_CHECK_UNDECIDED {pid}: needs agree true, a second checker and a decision")
        claimed = _year(d.get("claimed_year"), f"arrival check {pid} claimed_year")
        line = None
        for f in FIELDS:
            for ln in october[f][1:]:
                g = _parse(ln)
                if _key(f, g) == d.get("event_id") and g[ID_COL[f]] == pid:
                    line = (f, g)
        if line is None or str(line[1][ARR_COL[line[0]]]) != str(claimed):
            raise Stop(f"ARRIVAL_CHECK_EVENT {pid}: {d.get('event_id')} with arrival {claimed} is not an October event")
        v = d.get("verified_year")
        row = plan_by_star.get(pid)
        if v is None:
            if row:
                raise Stop(f"ARRIVAL_CHECK_CONFLICT {pid}: unverified, yet a redate row says {row['year']}")
            records.append({"star": pid, "event": d["event_id"], "verified": None, "action": "kept_unverified"})
            continue
        v = _year(v, f"arrival check {pid} verified_year")
        if not in_window(v):
            raise Stop(f"ARRIVAL_OUT_OF_WINDOW {pid}: verified {v} is outside the event window; the event would "
                       f"leave the sample - the author decides")
        if v == claimed:
            if row:
                raise Stop(f"ARRIVAL_CHECK_CONFLICT {pid}: verified {v} = claimed, yet a redate row says {row['year']}")
            records.append({"star": pid, "event": d["event_id"], "verified": v, "action": "confirmed"})
        else:
            if not row or row["year"] != v:
                raise Stop(f"ARRIVAL_CHECK_CONFLICT {pid}: verified {v}, but the redate rows say "
                           f"{row['year'] if row else 'nothing'} (one person_overrides arrival_year row is the path)")
            records.append({"star": pid, "event": d["event_id"], "verified": v, "action": "redated"})
    return records


# ------------------------------------------------------------------------------------------------ new rows
def new_line(field: str, header: list, r: dict) -> str:
    pid, year = r["person_id"], int(r["arrival_year"])
    school = str(r.get("dept_key") or "").split("_", 1)[0]
    if not school or school != r.get("school"):
        raise Stop(f"ACCEPT_SCHOOL {pid}: dept_key {r.get('dept_key')!r} vs school {r.get('school')!r}")
    if field == "econ":
        missing = [c for c in ECON_NEW_COLS if c not in header]
        if missing:
            raise Stop(f"ECON_HEADER {missing}")
        vals = {"event_id": f"{pid}:{year}", "star_id": pid, "school": school, "arrival_year": str(year),
                "arrival_source": SIGNED_ADD, "arrival_evidence": "strong",
                "reason": "R1 add list ACCEPT: " + str(r.get("basis") or "")[:200],
                "evidence_source": ADD_LIST_REPO_PATH}
    else:
        if header != CM_COLS:
            raise Stop(f"CHEMMATH_HEADER {field}: {header}")
        vals = {"field": field, "school": school, "author_id": pid, "display_name": r.get("name", ""),
                "arrival_corrected": str(year), "evidence_grade": "strong", "evidence_url": "",
                "signature": SIGNED_ADD}
    return _join([vals.get(c, "") for c in header])


# ------------------------------------------------------------------------------------------------ modes
def build_b0(a) -> dict:
    vs = _verdict_source(a.repo)
    src = vs.load(a.rank_tables)
    if src.kind != "B0":
        raise Stop(f"RANK_TABLES_KIND {src.kind}: --mode b0 needs B0 rank tables")
    corr = vs.read_corrections(a.corrections)
    files, decision, dropped_all = {}, {"dropped": [], "kept_by_author_ruling": [], "id_corrected": corr, "p05": {}}, []
    for f in FIELDS:
        text = (pathlib.Path(a.raw_0828) / f"events_{f}_cal2026-08-28.csv").read_bytes().decode("utf-8")
        lines, lines05, dropped = vs.filter_october_rows(f, text, corr, src)
        files[table_name(f)], files[table_name(f, True)] = _text(lines), _text(lines05)
        dropped_all += dropped
        decision["p05"][f] = {"events": len(lines) - 1, "p05_events": len(lines05) - 1}
    decision["dropped"], decision["kept_by_author_ruling"] = dropped_all, src.kept_by_author_ruling
    files[DECISION] = json.dumps(decision, ensure_ascii=False, indent=1).encode("utf-8")
    differ = [n for n, b in files.items() if (pathlib.Path(a.october) / n).read_bytes() != b]
    if differ:
        raise Stop(f"B0_NOT_OCTOBER {' '.join(differ)}")
    summary = {"result": "OK", "mode": "b0", "events": {f: decision["p05"][f]["events"] for f in FIELDS},
               "events_p05": {f: decision["p05"][f]["p05_events"] for f in FIELDS}, "files": sorted(files)}
    return {"files": files, "summary": summary}


def build_m(a) -> dict:
    vs = _verdict_source(a.repo)
    in_window = _in_window(a.repo)
    s = _json(a.addlist_summary)
    if s.get("result") != "OK":
        raise Stop(f"ADD_LIST_NOT_OK {pathlib.Path(a.addlist_summary).name}: result {s.get('result')} "
                   f"(the roster-gap events stay out until the add-list gate passes)")
    signed = load_signed(a.flips, a.add_list)
    flips, accept = signed["flips"], signed["accept"]
    src = vs.load(a.rank_tables)
    if src.kind != "M":
        raise Stop(f"RANK_TABLES_KIND {src.kind}: --mode m needs M rank tables")
    corr = vs.read_corrections(a.corrections)
    october = {f: _lines(pathlib.Path(a.october) / table_name(f)) for f in FIELDS}
    oct_decision = _json(pathlib.Path(a.october) / DECISION)
    oct_dropped = {d["star"] for d in oct_decision.get("dropped", [])}
    fixes, overrides = _read_csv(a.fixes), _read_csv(a.overrides)
    bad = sorted({r.get("fix", "") for r in fixes} - FIX_KINDS) + sorted({r.get("action", "") for r in overrides}
                                                                          - OVERRIDE_ACTIONS)
    if bad:
        raise Stop(f"UNKNOWN_FIX_KIND {' '.join(bad)}")

    # 1. October's lines through the signed verdicts
    main, removed, restored, absent = {}, [], [], []
    for f in FIELDS:
        text = (pathlib.Path(a.raw_0828) / f"events_{f}_cal2026-08-28.csv").read_bytes().decode("utf-8")
        try:
            lines, _, _ = vs.filter_october_rows(f, text, corr, src)
        except vs.VerdictMissing as e:
            raise Stop(f"VERDICT_MISSING {e.field} {e.author_id}") from None
        if lines[0] != october[f][0]:
            raise Stop(f"HEADER {f}: the 08-28 header differs from October's")
        oct_keys = [_key(f, _parse(ln)) for ln in october[f][1:]]
        oct_by_key = dict(zip(oct_keys, october[f][1:]))
        if len(oct_by_key) != len(oct_keys):
            raise Stop(f"OCTOBER_DUPLICATE_EVENT {f}")
        kept, back = [], []
        for ln in lines[1:]:
            k = _key(f, _parse(ln))
            if k in oct_by_key:
                if ln != oct_by_key[k]:
                    raise Stop(f"OCTOBER_LINE_DIFFERS {f} {k}")
                kept.append(ln)
            else:
                back.append(ln)
        kept_keys = [_key(f, _parse(ln)) for ln in kept]
        if kept_keys != [k for k in oct_keys if k in set(kept_keys)]:
            raise Stop(f"OCTOBER_ORDER {f}")
        drop_ids = {p for p, r in flips.items() if r["verdict"] == "DROP" and r["field"] == f}
        gone = [(k, _star(f, oct_by_key[k])) for k in oct_keys if k not in set(kept_keys)]
        not_drop = [k for k, star in gone if star not in drop_ids]
        should_go = [k for k in oct_keys if _star(f, oct_by_key[k]) in drop_ids and k in set(kept_keys)]
        if not_drop or should_go:
            raise Stop(f"DROPPED_NOT_THE_DROP_STARS {f}: removed {not_drop} kept {should_go}")
        removed += [{"field": f, "event": k, "star": star} for k, star in gone]
        with_event = {star for _, star in gone} | {_star(f, ln) for ln in kept}
        for pid in sorted(drop_ids - with_event):
            if pid not in oct_dropped:
                raise Stop(f"DROP_WITHOUT_EVENT {pid}: a DROP star with no October event that October did not drop")
            absent.append({"field": f, "star": pid})
        for ln in back:
            pid = _star(f, ln)
            r = flips.get(pid)
            if not r or r["verdict"] != "KEEP" or r.get("flip") != "out->in" or pid not in oct_dropped:
                raise Stop(f"RESTORED_NOT_SIGNED {f} {pid}: an 08-28 event outside October needs a KEEP out->in "
                           f"verdict for a star October dropped")
            restored.append({"field": f, "event": _key(f, _parse(ln)), "star": pid})
        main[f] = [lines[0]] + kept + back

    # 2. redates (fixes_1001 redate + person_overrides arrival_year) and the S14 arrival checks
    plan = signed_redates(fixes, overrides)
    plan_by_star = {p["star"]: p for p in plan}
    for p in plan:
        if not in_window(p["year"]):
            raise Stop(f"ARRIVAL_OUT_OF_WINDOW {p['star']}: {p['source']} {p['year']} is outside the event window; "
                       f"the event would leave the sample - the author decides")
    checks = check_arrival_checks(a.arrival_checks, october, plan_by_star, in_window)
    to_apply = []
    for p in plan:
        r, add = flips.get(p["star"]), signed["add_by_id"].get(p["star"])
        if r and r["verdict"] == "KEEP":
            to_apply.append(p)
        elif add:          # an add-list person (ACCEPT or REJECT): the signed add list already carries the year
            if _year(add["arrival_year"], f"add list {p['star']}") != p["year"]:
                raise Stop(f"REDATE_VS_ADD_LIST {p['star']}: {p['source']} {p['year']} != add list {add['arrival_year']}")
        else:
            raise Stop(f"REDATE_NOT_A_KEPT_STAR {p['star']} ({p['source']})")
    main, redated = apply_redates(main, to_apply)
    for r in redated:
        got = src.row(r["field"], r["star"])["arrival_true"]
        if got != r["new_year"]:
            raise Stop(f"RANK_ARRIVAL {r['star']}: the rank tables carry arrival {got}, the signed redate "
                       f"{r['new_year']} (rerun the rank chain)")

    # 3. the signed add list, in file order
    added = []
    for f in FIELDS:
        header = _parse(main[f][0])
        rows = [r for r in accept if r["field"] == f]
        want, got = {r["person_id"] for r in rows}, {e["author_id"] for e in src.new_events(f)}
        if want != got:
            raise Stop(f"NEW_STARS_NOT_SIGNED {f}: tables only {sorted(got - want)} add list only {sorted(want - got)}")
        for r in rows:
            pid, year = r["person_id"], _year(r["arrival_year"], f"add list {r['person_id']}")
            if not in_window(year):
                raise Stop(f"ARRIVAL_OUT_OF_WINDOW {pid}: add list {year} - the author decides")
            row = src.row(f, pid)
            if row["arrival_true"] != year or row["school"] != r["school"]:
                raise Stop(f"RANK_VS_ADD_LIST {pid}: rank ({row['arrival_true']}, {row['school']}) "
                           f"!= add list ({year}, {r['school']})")
            # October's tables are CRLF: a new row ends like the header, or the table mixes line ends and
            # the CSV sniffers downstream (prodlib, the econ union) cannot read it (j1a-17)
            ln = new_line(f, header, r) + ("\r" if main[f][0].endswith("\r") else "")
            main[f].append(ln)
            added.append({"field": f, "event": _key(f, _parse(ln)), "star": pid})

    # 4. every event star is signed exactly once; top-5% from the source; fixes_1001 asserts
    p05 = {}
    for f in FIELDS:
        stars = [_star(f, ln) for ln in main[f][1:]]
        dup = sorted({x for x in stars if stars.count(x) > 1})
        want = {p for p, r in flips.items() if r["verdict"] == "KEEP" and r["field"] == f}
        want |= {r["person_id"] for r in accept if r["field"] == f}
        if dup or set(stars) != want:
            raise Stop(f"EVENT_STARS_NOT_SIGNED {f}: twice {dup} unsigned {sorted(set(stars) - want)} "
                       f"without event {sorted(want - set(stars))}")
        p05[f] = [main[f][0]] + [ln for ln in main[f][1:] if src.p05(f, _star(f, ln))]
    p05_ids = {_star(f, ln) for f in FIELDS for ln in p05[f][1:]}
    for r in fixes:
        pid, kind = r["author_id"], r["fix"]
        if kind == "p05_out" and pid in p05_ids:
            raise Stop(f"FIXES_P05_OUT {pid}: fixes_1001 p05_out, yet in a top-5% table")
        if kind == "drop" and (pid not in flips or flips[pid]["verdict"] != "DROP"):
            raise Stop(f"FIXES_DROP {pid}: fixes_1001 drop is not a flips DROP")
        if kind == "below_cut_1001" and pid not in flips:
            raise Stop(f"FIXES_BELOW_CUT {pid}: no flips verdict")

    # 5. aliases from the calls stage
    rank_adds = _json(pathlib.Path(a.calls) / "rank_adds.json")
    if not isinstance(rank_adds, dict) or not all(isinstance(v, list) for v in rank_adds.values()):
        raise Stop("RANK_ADDS_SHAPE rank_adds.json is not {main_id: [alias ids]}")
    event_stars = {_star(f, ln) for f in FIELDS for ln in main[f][1:]}
    aliases = sorted({(k, x) for k, v in rank_adds.items() for x in v})
    bad = sorted({x for k, x in aliases if x == k or x in event_stars})
    if bad:
        raise Stop(f"ALIAS_IS_A_STAR {' '.join(bad)}")
    for r in accept:
        extra = [x for x in str(r.get("all_ids") or "").split("|") if x and x != r["person_id"]]
        missing = [x for x in extra if x not in rank_adds.get(r["person_id"], [])]
        if missing:
            raise Stop(f"ALIAS_MISSING {r['person_id']}: {' '.join(missing)} not in rank_adds.json")

    # 6. outputs
    counts = {"schema": COUNTS_SCHEMA, "config": "M", "events": {f: len(main[f]) - 1 for f in FIELDS},
              "events_p05": {f: len(p05[f]) - 1 for f in FIELDS}}
    counts["events_total"] = sum(counts["events"].values())
    counts["candidates"] = signed["n_flips"]
    differs = sorted(_star(f, ln) for f in FIELDS for ln in main[f][1:]
                     if _parse(ln)[ARR_COL[f]] != str(src.row(f, _star(f, ln))["arrival_true"]))
    decision = {"schema": DECISION_SCHEMA, "config": "M", "dropped": removed, "absent_in_october": absent,
                "redated": redated, "restored": restored, "added": added, "arrival_checks": checks,
                "id_corrected": corr}
    files = {}
    for f in FIELDS:
        files[table_name(f)], files[table_name(f, True)] = _text(main[f]), _text(p05[f])
    files[DECISION] = (json.dumps(decision, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    files["counts.json"] = (json.dumps(counts, indent=1) + "\n").encode("utf-8")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["person_id", "alias_id", "source"])
    w.writerows([(k, x, ALIAS_SOURCE) for k, x in aliases])
    files["star_aliases_r1.csv"] = buf.getvalue().encode("utf-8")
    summary = {"result": "OK", "mode": "m", "counts": counts,
               "dropped": [d["event"] for d in removed], "absent_in_october": [d["star"] for d in absent],
               "redated": [f"{r['old_event']}->{r['new_event']}" for r in redated],
               "restored": [d["event"] for d in restored], "n_added": len(added),
               "arrival_checks": [f"{c['star']}:{c['action']}" for c in checks],
               "arrival_differs_from_rank": differs, "n_aliases": len(aliases)}
    return {"files": files, "summary": summary}


# ------------------------------------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    if os.environ.get("SAR_HOST", "").strip() not in AWS_HOSTS:
        raise SystemExit("R1 rule (design v3 §4): events_r1.py runs only on an R1 AWS instance ($SAR_HOST)")
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--mode", required=True, choices=("m", "b0"))
    for n in ("--repo", "--rank-tables", "--raw-0828", "--corrections", "--october", "--out"):
        ap.add_argument(n, required=True)
    for n in M_ONLY:
        ap.add_argument("--" + n.replace("_", "-"))
    a = ap.parse_args(argv)
    given = [n for n in M_ONLY if getattr(a, n) is not None]
    if a.mode == "m" and len(given) != len(M_ONLY):
        ap.error("--mode m needs " + " ".join("--" + n.replace("_", "-") for n in M_ONLY if n not in given))
    if a.mode == "b0" and given:
        ap.error("--mode b0 takes no " + " ".join("--" + n.replace("_", "-") for n in given))
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        res = build_m(a) if a.mode == "m" else build_b0(a)
    except Stop as e:
        (out / "summary.json").write_text(json.dumps({"result": "STOP", "mode": a.mode, "problem": str(e)},
                                                     ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (out / "RESULT.txt").write_text("STOP\n", encoding="utf-8")
        raise SystemExit(f"STOP {e}") from None
    for name, data in res["files"].items():
        (out / name).write_bytes(data)
    (out / "summary.json").write_text(json.dumps(res["summary"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "RESULT.txt").write_text("OK\n", encoding="utf-8")
    ev = res["summary"].get("counts", res["summary"]).get("events")
    print("RESULT OK " + a.mode + " " + " ".join(f"{f}={ev[f]}" for f in FIELDS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
