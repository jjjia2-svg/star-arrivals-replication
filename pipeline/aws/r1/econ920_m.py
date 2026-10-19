#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 F11 (+ F13 hook, J0-MEAS.3h, J0-MEAS.3i, V3-NET hook): economics for run config M through the
October econ920 machinery, which is imported and never edited (EC2 only).

    econ920_m.py --execute --config config/r1/M.json --events DIR --rank-tables DIR --calls DIR
                 --roster-econ FILE --patch-extra FILE --patch-october FILE --out STAGE_OUT
    ($SAR_OUT_ROOT = an empty scratch root, or one that holds an earlier econ920_report.json)

What it runs, in order, in one root:
  1. October's controls c1a, gdose (the population measurement), c1b, c2, c3 through run_econ920's own
     functions (a control that is not CLEAR stops the stage, exit 1; CLEAR controls of an earlier run
     in the same root are reused). The controls report goes to STAGE_OUT/controls_report_econ920_m.json.
     Their precondition step is control_preconditions: October's minus the checks of October's own build
     tables, which are products the M sandbox moved away (M review #2; the B0 proof keeps October's step).
  2. The M phase (m_phase, ORDER below). Every input comes from a flag or from the run config; every
     set it acts on comes from the data (plan_m):
       removed_old       the 08-28 events of signed DROP stars that are not in the age table (left at the
                         ledger as October's three did)
       REGEN             the id-corrected events (A5091326353) ∪ the re-dated events ∪ the new (ACCEPT) events:
                         ONE prodlib run on the M tables rebuilds them, spliced through filter_events,
                         listed once each in the provenance table (the id-correction method, h3)
       removed_new_*     every age-table event that does not stay as it is (A5044432173, a DROP star's, a
                         REGEN star's old one) leaves before the ledger stage (build_econ_shadow)
       restored          A5110738002's 08-28 event stays (not regenerated); its rows are the frozen rows
     The ledger: the ported ledger stage, minus removed_old, the id correction, the re-dates in place
     (cols 0 and 3, exactly one line each, h2: arrival moves), then events_r1's new lines byte for byte;
     its event set must equal the M table's. The star set: DROP stars out, the id-corrected star re-keyed, a re-dated star
     keeps its first-publication year (academic_age moves with the arrival), new stars with the rank's
     aage (a new star's frozen U4 candidate row, if any, is replaced in place by its event row; one star
     with two events STOPs); existing events keep their frozen ages and every difference to the rank's
     aage is reported. The star set is built before the prodlib run (REGEN-AGE):
     in M prodlib's star set takes its ages (restake aage rewritten for every REGEN star, ids/old/new in
     regeneration.prodlib_restake) and its config the 08-15 first-publication rule the union clone and the kept
     July / fn-fix rows use (star_set_academic_age + panel_then_wfp on the clone's U3 panel;
     regeneration.first_pub_switch), so the frame has one age_gap rule (regeneration.age_gap_rule, per event).
     B0 keeps October's restake table and works_robust config.
     V3-NET (switch network_freeze) filters the clone's INPUT network frame - the union rung rebuilds a
     dropped 'both' relation as dept_only, and the G-DOSE prediction must use exactly the frame the
     clone reads - and its dropped relations are set aside in union_rows_proof's reference. Each of the
     frame's three row groups is classified on the graph that built it (split_net1 / freeze_graphs): the
     July rows, the 2026-08-15 prodlib rows of the fn-fix events (that run's own frozen config) and the
     REGEN rows (this run's prodlib config). After the
     union rung: (a)+(b) post-filter, rows whose incumbent is a NEW M star (any alias) removed
     ('incumbent_is_star_r1'), union_rows_proof on the UNFIXED frame, the 3i coverage gate (M: STOP with
     ids, exit 3), the F13 dose post-step (switch dose_mode; the fixed pre-y re-installed, then
     dose_rows_proof as an in-run gate), the chain (ledger -> p1-econ -> p2-econ -> make_slim; no split
     stage in M, C10) and freeze_m.
  3. freeze_m writes ONLY under STAGE_OUT: frames_econ/ (data/frames basenames + MANIFEST.sha256 with
     paths relative to STAGE_OUT), afar_econ/ (the four names run_cal_afar stages), pairs/,
     build_report_econ_m.json (pin key for assemble_frames: build_report_econ_m.json#m.pairs_unified;
     m.regeneration.prodlib.secs is the one-run prodlib measurement) and report_gdose_m.json (3h).

G-DOSE (3h, ruling h4): the draw is predicted on the clone's input before the run; the override is used
only when the prediction is FAIL and the run config's ruling gdose_override is 'pass_h4' (a missing
ruling is a STOP); run_econ920.override_is_justified is the evidence gate; M's record cites v3 §6 /
v2 #16 (B0 keeps October's string byte for byte); an unexplained failure STOPs (GDOSE_UNEXPLAINED, ids).
In M only, the gate's G_ROW condition is "0 UNEXPLAINED G_ROW mismatches and G_SUM ok" (classify_g_row over
the clone's full list, read by clone_g_row_capture); B0 keeps October's verdict byte for byte.

STOPs: exit 3 with STAGE_OUT/stop_report_<name>.json (code, ids; ids are OpenAlex / event ids only) and
RESULT.txt 'STOP <code>'. October's run_econ920.py / econ920_lib.py / the clone are imported unedited;
nothing is written under data/cal2026-10, data/frames, analysis/expected or the legacy trees. The
patch file build_econ_shadow needs inside the repository is written to output/cal_intermediates/r1/.

Out of scope (since 2026-10-15): F20, the new-star departure ledger and departure frames - the
paper prints no star-departure robustness.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import copy
import csv
import dataclasses
import datetime
import io
import json
import math
import os
import pathlib
import re
import shutil
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
_MARK = pathlib.Path("pipeline/frames/cal2026-10/econ920/econ920_lib.py")


def _find_repo() -> pathlib.Path:
    """The checkout this file sits in, else $REPO_DIR: J1a runs a copy at $WORK/econ920_m.py (run_stages),
    where HERE.parents[2] does not exist or is not the checkout (M review #1; chemmath_m.py's rule)."""
    cands = []
    if len(HERE.parents) >= 3 and (HERE.parents[2] / _MARK).is_file():      # <repo>/pipeline/aws/r1
        cands.append(HERE.parents[2])
    env = os.environ.get("REPO_DIR", "").strip()
    if env:
        cands.append(pathlib.Path(env))
    for c in cands:
        if (c / _MARK).is_file():
            return c.resolve()
    raise SystemExit("econ920_m: cannot find the repository (run it from the checkout or set $REPO_DIR)")


REPO = _find_repo()
ECON920 = REPO / "pipeline" / "frames" / "cal2026-10" / "econ920"
# the checkout's directories go before a staged copy's own directory ($WORK, which holds other stages' copies)
for _p in (str(REPO), str(REPO / "pipeline" / "aws" / "r1"), str(ECON920)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import econ920_lib as L                                                  # noqa: E402  (October, unedited)
import run_econ920 as R                                                  # noqa: E402  (October, unedited)
import missing_persons                                                   # noqa: E402  (W1-MISSING)
import network_freeze as nf                                              # noqa: E402  (W1-NET)
import r1_dose_excl                                                      # noqa: E402  (W1-DOSEECON)
import verdict_source                                                    # noqa: E402  (W1-VSRC)
from pipeline.lib import r1_config                                       # noqa: E402  (W1-CFG)
from pipeline.lib.paths import OUT_ROOT_ENV                              # noqa: E402
from pipeline.lib.paths import derived_root as _derived_root             # noqa: E402  (the root the union clone reads)

pa_stage = L.pa_stage
fs08 = L.fs08
sha = L.sha

HOSTS = ("ec2-r1-test", "ec2-r1")
REPORT_NAME = "econ920_m_report.json"
BUILD_REPORT = "build_report_econ_m.json"
GDOSE_REPORT = "report_gdose_m.json"
CONTROLS_REPORT = "controls_report_econ920_m.json"
DECISION = "events_decision_2026-10.json"
ALIASES = "star_aliases_r1.csv"
FIELDS = ("econ", "chemistry", "math_stats")
LEDGER_HDR = ["event_id", "star_id", "school", "arrival_year"]
PRE_Y_REL = f"{L.ECON}/data/analysis_frame_dept_p01_econ920_2026-08-13.csv"
REL_REL = f"{L.ECON}/data/relationships.csv"
UNION_REPORT_REL = f"{L.ECON}/data/build_report.json"
NEW_EVENTS_REL = f"{L.ECON}/data/new_events_econ.csv"
LEDGER_REL = f"{L.ECON}/data/event_ledger_fnfix.csv"
SUP_FNFIX_REL = f"{L.ECON}/data/edges_supplement_fnfix.jsonl"
#: the frozen 2026-08-15 econ prodlib config: the builder of the fn-fix events' network rows
#: (01_merge_inputs.py appends them after the July rows; run_controls.py C1e reproduces them byte for byte)
FNFIX_CONFIG_REL = f"{L.ECON}/config/econ_fnfix.json"
#: V3-NET's row groups of net1, in net1's order (July rows, the 08-15 prodlib rows, the spliced REGEN block)
FREEZE_PARTS = ("july", "fnfix", "regenerated")
PATCH_DIR = REPO / "output" / "cal_intermediates" / "r1"
#: October roots nothing here may write into
OCTOBER_ROOTS = (L.CAL10, REPO / "data" / "frames", REPO / "analysis" / "expected",
                 REPO / "output" / "cal_intermediates" / "cal2026-10")
CONTROL_PHASES = ("c1a", "gdose", "c1b", "c2", "c3")

#: October's G-DOSE ruling string, captured at import; B0 keeps it byte for byte
OCTOBER_OVERRIDE_RULING = R.OVERRIDE_RULING
M_OVERRIDE_RULING = "v3 §6 / v2 #16 (h4): passes, as in October; J0 measures the draw and reports it"
GDOSE_RULING_VALUE = "pass_h4"
PROVENANCE_SOURCE = {"corrected": "regenerated_by_prodlib_star_id_correction_2026-10",
                     "redated": "regenerated_by_prodlib_redate_r1",
                     "added": "regenerated_by_prodlib_new_star_r1"}
_ID = re.compile(r"^(P_)?A\d+(:\d{4})?$")
_GDOSE_ID = re.compile(r"^A\d+(:\d{4})?$")
GDOSE_CONDITIONS = ("population_measured", "draw_predicted_FAIL", "prediction_matches_run",
                    "every_failing_relation_is_a_frozen_population_residual", "failure_is_gdose_only",
                    "G_ROW_zero_mismatches_and_G_SUM_ok", "gate_was_intercepted_exactly_once")
#: October's G_ROW condition, and the one M uses in its place (gdose_verdict)
OCTOBER_G_ROW_CONDITION = "G_ROW_zero_mismatches_and_G_SUM_ok"
M_G_ROW_CONDITION = "G_ROW_zero_unexplained_mismatches_and_G_SUM_ok"
#: classify_g_row's classes: the two explained ones, then every reason a mismatch stays unexplained
G_ROW_EXPLAINED = ("outcome_new_event_outside_u5", "pub_count_source_new_event_outside_u5", "dose_population_residual")
G_ROW_UNEXPLAINED = ("capture_not_tied_to_clone_count", "row_missing_in_old", "na_mismatch", "age_gap",
                     "dose_not_population_residual", "outcome_old_event", "outcome_inside_u5", "other")
#: the clone's G_ROW outcome columns; 04_rebuild_y.py overwrites only L.Y_SWAPPED_BY_04 of them
G_ROW_OUTCOME_COLS = ("fwci_frac", "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean",
                      "fwci_mean_ex_star")
G_ROW_RULE = ("M: every union-clone G_ROW mismatch explained, and G_SUM ok. Explained: (1) a y column "
              "04_rebuild_y.py overwrites (fwci_frac, fwci_frac_ex_star, fwci_mean, fwci_mean_ex_star) on a row "
              "of an event in the clone's provenance set, incumbent outside U5's output table; (2) pub_count / "
              "pub_count_ex_star on such a row (the clone counts from the R1 patch, prodlib from the snapshot; 04 "
              "keeps pub_count, as in October); (3) dose_topic on a relation of October's G-DOSE residual table, "
              "that difference (1e-12) on all its rows")
#: every key report_gdose_m.json / stop_report_gdose.json may carry (counts, codes, ids, column names, the ruling)
GDOSE_KEYS = frozenset({
    "schema", "config", "code", "ruling", "override", "ids", "n_ids", "population", "predicted", "actual",
    "conditions", "n", "share_exact_1e-9", "max_abs_diff", "n_gt_0.01", "n_gt_0.05", "gate", "drawn",
    "population_relations", "G_DOSE", "G_ROW", "missing_side", "sampled_both", "mismatches",
    "dose_tolerated_le_0.01", "fill_divergence", "gate_overridden", "exit", *GDOSE_CONDITIONS,
    M_G_ROW_CONDITION, "g_row", "rule", "captured", "n_reported", "n_mismatches", "n_explained", "n_unexplained",
    "explained", "unexplained", *G_ROW_EXPLAINED, *G_ROW_UNEXPLAINED, "n_cells", "n_relations", "cells", "year",
    "columns", "old", "new"})


class MStop(Exception):
    """A contradiction or a failed gate: the stage stops (exit 3) and the author or an engineer decides.
    `ids` are OpenAlex / event ids only; `written` = the stop report was written by the step itself."""

    def __init__(self, code: str, ids=(), detail: str = "", *, name: str = "econ_m", written: bool = False):
        super().__init__(f"{code} {' '.join(map(str, list(ids)[:50]))} {detail}".strip())
        self.code, self.ids, self.detail, self.name, self.written = code, list(ids), detail, name, written


def log(msg: str) -> None:
    print(f"[econ920_m] {msg}", flush=True)


def _flat_ids(obj) -> list[str]:
    """Event / OpenAlex ids out of strings, (pid, event) tuples and lists; anything else is dropped."""
    out: list[str] = []
    if isinstance(obj, str):
        if _ID.match(obj):
            out.append(obj)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for v in obj:
            out.extend(_flat_ids(v))
    return out


def _inside(p: pathlib.Path, roots) -> pathlib.Path | None:
    p = pathlib.Path(p).resolve()
    for r in roots:
        r = pathlib.Path(r).resolve()
        if p == r or r in p.parents:
            return r
    return None


# ================================================================================================ the plan
@dataclasses.dataclass
class Plan:
    """What the M (or October) economics build does to October's frozen inputs, read from the data."""
    name: str
    m_events: list[str]                     # the run's econ event table, table order
    lines: dict[str, bytes]                 # event -> its table line (no line end)
    schools: dict[str, str]
    regen: dict[str, dict]                  # new event -> {kind, old, star, school, name}
    removed_old: list[str]
    removed_new_events: list[str]
    removed_new_stars: list[str]
    restored: list[str]
    unstar: list[str]                       # signed DROP stars of every field: non-stars everywhere
    new_stars: list[str]                    # every field's ACCEPT stars (events_decision 'added')
    redates: dict[str, str]                 # econ old -> new event
    ledger_redates: dict[str, str]
    ledger_corrections: dict
    ledger_appends: list[str]
    corr_rows: list[dict]

    def summary(self) -> dict:
        return {"name": self.name, "events": len(self.m_events),
                "regen": {e: v["kind"] for e, v in sorted(self.regen.items())},
                "removed_old": sorted(self.removed_old), "removed_new_events": sorted(self.removed_new_events),
                "removed_new_stars": sorted(self.removed_new_stars), "restored": sorted(self.restored),
                "unstar": sorted(self.unstar), "new_stars": sorted(self.new_stars),
                "ledger_redates": dict(self.ledger_redates), "ledger_appends": list(self.ledger_appends),
                "ledger_corrections": dict(self.ledger_corrections.get("events", {}))}


def read_ledger_table(p) -> tuple[list[str], list[tuple[str, str, str, bytes]]]:
    """A ledger-shaped econ table -> (header cells, [(event_id, star_id, school, raw line)])."""
    raw = pathlib.Path(p).read_bytes()
    parts = raw.split(b"\n")
    hdr = L.cells_of(parts[0])
    if hdr[:4] != LEDGER_HDR:
        raise MStop("TABLE_SHAPE", [], f"{pathlib.Path(p).name}: header {hdr[:4]} != {LEDGER_HDR}")
    rows = []
    for ln in parts[1:]:
        if not ln:
            continue
        c = L.cells_of(ln)
        if c[0] != f"{c[1]}:{int(c[3])}":
            raise MStop("TABLE_EVENT_ID", [c[0]], "event_id is not star:arrival_year")
        rows.append((c[0], c[1], c[2], ln))
    return hdr, rows


def age_table_events(p) -> dict[str, str]:
    """new_events_econ.csv -> {event: star}."""
    return {f"{r['author_id']}:{int(r['arrival'])}": r["author_id"] for r in L.read_rows(pathlib.Path(p))}


def build_plan(*, name: str, e0828: list[str], new_age: dict[str, str], m_rows, corr_rows: list[dict],
               redated: dict[str, str], added: list[str], restored: list[str], removal_signed: set[str],
               unstar: set[str], new_stars: set[str], names: dict[str, str] | None = None) -> Plan:
    """The economics plan from the tables (no literal counts). removal_signed = the stars whose 08-28 event
    may leave (M: the econ DROP stars; October: the stars of its decision 'dropped')."""
    names = names or {}
    m_events = [e for e, _s, _sc, _ln in m_rows]
    if len(set(m_events)) != len(m_events):
        raise MStop("TABLE_DUPLICATE_EVENT", sorted({e for e in m_events if m_events.count(e) > 1}))
    m_set, e0828_set, age = set(m_events), set(e0828), dict(new_age)
    lines = {e: ln for e, _s, _sc, ln in m_rows}
    schools = {e: sc for e, _s, sc, _ln in m_rows}
    stars_of = {e: s for e, s, _sc, _ln in m_rows}
    corr_stars = {r["old_id"]: r["new_id"] for r in corr_rows}
    regen: dict[str, dict] = {}

    def meta(new: str, kind: str, old: str | None) -> dict:
        star = new.split(":")[0]
        nm = names.get(star) or (names.get(old.split(":")[0]) if old else None) or ""
        return {"kind": kind, "old": old, "star": star, "school": schools.get(new, ""), "name": nm}

    corr_events = {}
    for e in sorted(e0828_set | set(age)):
        star, year = e.split(":")
        if star in corr_stars:
            corr_events[e] = f"{corr_stars[star]}:{year}"
    for old, new in corr_events.items():
        if new in m_set:
            regen[new] = meta(new, "corrected", old)
    for old, new in redated.items():
        if new not in m_set or old not in e0828_set | set(age):
            raise MStop("REDATE_NOT_IN_TABLES", [old, new])
        if new in regen:
            raise MStop("REDATE_AND_CORRECTION", [new])
        regen[new] = meta(new, "redated", old)
    for e in added:
        if e not in m_set or e in e0828_set or e in age:
            raise MStop("ADDED_EVENT_NOT_NEW", [e])
        regen[e] = meta(e, "added", None)
    regen_old = {v["old"] for v in regen.values() if v["old"]}
    kept = ((e0828_set | set(age)) & m_set) - set(regen)
    unexplained = sorted(m_set - kept - set(regen))
    if unexplained:
        raise MStop("M_EVENT_UNEXPLAINED", unexplained, "an M event that is neither kept nor regenerated")
    for e in restored:
        if e not in kept or e not in e0828_set:
            raise MStop("RESTORED_NOT_KEPT", [e], "a restored event keeps its frozen 08-28 rows")
    removed_new_events = sorted(e for e in age if e not in kept)
    removed_old = sorted(e for e in e0828_set if e not in age and e not in kept and e not in regen_old)
    bad = [e for e in removed_old if e.split(":")[0] not in removal_signed]
    bad += [e for e in removed_new_events
            if e not in regen_old and age[e] not in removal_signed and e in e0828_set]
    if bad:
        raise MStop("REMOVAL_NOT_SIGNED", sorted(bad), "an 08-28 event leaves without a signed DROP")
    gone_new = set(removed_new_events)
    ledger_redates = {o: n for o, n in redated.items() if o not in gone_new}
    ledger_corr_ev = {o: n for o, n in corr_events.items() if n in regen and o not in gone_new}
    ledger_corrections = {"events": ledger_corr_ev,
                          "stars": {o.split(":")[0]: n.split(":")[0] for o, n in ledger_corr_ev.items()}} \
        if ledger_corr_ev else {"events": {}, "stars": {}}
    appends = [e for e in m_events if e in regen and (regen[e]["kind"] == "added" or regen[e]["old"] in gone_new)]
    for e in m_events:                                    # the M table carries the corrected star ids
        if stars_of[e] != e.split(":")[0]:
            raise MStop("TABLE_EVENT_ID", [e])
    return Plan(name=name, m_events=m_events, lines=lines, schools=schools, regen=regen,
                removed_old=removed_old, removed_new_events=removed_new_events,
                removed_new_stars=sorted({age[e] for e in removed_new_events}), restored=sorted(restored),
                unstar=sorted(unstar), new_stars=sorted(new_stars), redates=dict(redated),
                ledger_redates=ledger_redates, ledger_corrections=ledger_corrections, ledger_appends=appends,
                corr_rows=list(corr_rows))


def _json(p) -> dict:
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def plan_m(*, events_dir, flips, corrections, e0828_table, new_events_csv, names=None) -> Plan:
    """M's plan: events_r1's econ table + decision, the signed flips, the star-id corrections, the frozen
    08-28 econ table and the frozen age table."""
    events_dir = pathlib.Path(events_dir)
    dec = _json(events_dir / DECISION)
    if dec.get("schema") != "sar.r1.events_decision.v1" or dec.get("config") != "M":
        raise MStop("DECISION_SHAPE", [], f"{DECISION} is not an M events_r1 decision")
    corr_all = L.read_rows(pathlib.Path(corrections))
    if dec.get("id_corrected") != {r["old_id"]: r["new_id"] for r in corr_all}:
        raise MStop("CORRECTIONS_DIFFER", sorted(dec.get("id_corrected") or {}),
                    "events_r1 applied other star-id corrections than this table")
    rows = _json(flips)["rows"]
    drop = {r["person_id"]: r["field"] for r in rows if r["verdict"] == "DROP"}
    _h, m_rows = read_ledger_table(events_dir / "events_econ_cal2026-10.csv")
    _h0, rows0828 = read_ledger_table(e0828_table)
    return build_plan(
        name="M", e0828=[e for e, *_ in rows0828], new_age=age_table_events(new_events_csv), m_rows=m_rows,
        corr_rows=[r for r in corr_all if r["field"] == "econ"],
        redated={r["old_event"]: r["new_event"] for r in dec.get("redated", []) if r["field"] == "econ"},
        added=[d["event"] for d in dec.get("added", []) if d["field"] == "econ"],
        restored=[d["event"] for d in dec.get("restored", []) if d["field"] == "econ"],
        removal_signed={p for p, f in drop.items() if f == "econ"}, unstar=set(drop),
        new_stars={d["star"] for d in dec.get("added", [])}, names=names)


def plan_october(v2: pathlib.Path, names=None) -> Plan:
    """October's plan through the same builder (the econ920_null switch-off proof): October's tables,
    REGEN = the id-corrected event, removed_old = October's dropped events, nothing re-dated or added."""
    dec = _json(L.CAL10 / DECISION)
    _h, m_rows = read_ledger_table(L.EVENTS_OCT)
    _h0, rows0828 = read_ledger_table(L.EVENTS_0828)
    return build_plan(
        name="october", e0828=[e for e, *_ in rows0828],
        new_age=age_table_events(v2 / L.ECON / "data/new_events_econ.csv"), m_rows=m_rows,
        corr_rows=[r for r in L.read_rows(L.STAR_ID_CORRECTIONS) if r["field"] == "econ"], redated={}, added=[],
        restored=[], removal_signed={d["star"] for d in dec["dropped"] if d["field"] == "econ"},
        unstar=set(), new_stars=set(), names=names)


def check_redates_map(rmap, redated: dict[str, str]) -> dict:
    """The run config's re-date map: one row per re-dated econ event, {new, firstpub_redate, decided};
    firstpub_redate is required and only 'keep' (h2: the arrival moves, the first-publication year
    does not) is accepted."""
    if not redated:
        if rmap:
            raise MStop("REDATES_MAP_EXTRA", sorted(rmap))
        return {}
    if not isinstance(rmap, dict):
        raise MStop("REDATES_MAP_MISSING", sorted(redated), "the run config carries no 'redates' map")
    out = {}
    for old, new in sorted(redated.items()):
        row = rmap.get(old)
        if not isinstance(row, dict):
            raise MStop("REDATES_MAP_MISSING", [old])
        if row.get("new") != new:
            raise MStop("REDATES_MAP_MISMATCH", [old, new])
        if "firstpub_redate" not in row:
            raise MStop("REDATE_FIRSTPUB_MISSING", [old])
        if row["firstpub_redate"] != "keep":
            raise MStop("REDATE_FIRSTPUB_NOT_KEEP", [old], f"firstpub_redate {row['firstpub_redate']!r}")
        out[old] = dict(row)
    extra = sorted(set(rmap) - set(redated))
    if extra:
        raise MStop("REDATES_MAP_EXTRA", extra)
    return out


def check_corrections(corr_rows: list[dict], redate_stars: set[str]) -> None:
    """A star-id correction that maps an id to itself, or that names a re-dated star, is a STOP."""
    for r in corr_rows:
        if r["old_id"] == r["new_id"]:
            raise MStop("CORRECTION_SELF", [r["old_id"]])
        hit = sorted({r["old_id"], r["new_id"]} & set(redate_stars))
        if hit:
            raise MStop("CORRECTION_REDATED", hit)


# ================================================================================================ the ledger
def ledger_redate(blob: bytes, redates: dict[str, str]) -> tuple[bytes, dict]:
    """Rewrite the event id (col 0) and arrival year (col 3) of each re-dated line; every other byte is
    kept ('\\r' included). Exactly one line per re-date, else a STOP."""
    hits = collections.Counter()
    out = []
    for i, ln in enumerate(blob.split(b"\n")):
        if i == 0 or not ln:
            out.append(ln)
            continue
        text = ln.decode("utf-8")
        c = next(csv.reader([text.rstrip("\r")]))
        e = c[0]
        if e in redates:
            new = redates[e]
            star, old_y = e.split(":")
            nstar, new_y = new.split(":")
            if nstar != star or c[1] != star or c[3] != old_y:
                raise MStop("REDATE_LEDGER_LINE", [e, new])
            prefix = f"{c[0]},{c[1]},{c[2]},{c[3]},"
            if not text.startswith(prefix):
                raise MStop("REDATE_NOT_IN_PLACE", [e])
            text = f"{new},{c[1]},{c[2]},{new_y}," + text[len(prefix):]
            hits[e] += 1
        out.append(text.encode("utf-8"))
    bad = sorted(e for e in redates if hits[e] != 1)
    if bad:
        raise MStop("REDATE_LEDGER_HITS", bad, f"{ {e: hits[e] for e in bad} } lines (want exactly one)")
    return b"\n".join(out), {"redated_lines": dict(hits)}


def ledger_events(blob: bytes) -> list[str]:
    return [next(csv.reader([ln.decode("utf-8").rstrip("\r")]))[0]
            for ln in blob.split(b"\n")[1:] if ln]


def finish_ledger(blob: bytes, *, redates: dict[str, str], appends: list[bytes], m_events: list[str]
                  ) -> tuple[bytes, dict]:
    """Re-date in place, append events_r1's new lines byte for byte, each ended like the ledger's own lines
    (the 08-28 ledger is CRLF, events_r1 writes its new lines LF; duckdb cannot sniff a mixed file); the
    ledger's event set must be the M table's."""
    blob, rec = ledger_redate(blob, redates)
    eol = b"\r\n" if blob.split(b"\n", 1)[0].endswith(b"\r") else b"\n"
    if appends:
        if not blob.endswith(b"\n"):
            blob += eol
        for ln in appends:
            ln = ln[:-1] if ln.endswith(b"\r") else ln
            if b"\n" in ln or b"\r" in ln:
                raise MStop("LEDGER_APPEND_SHAPE", [])
            blob += ln + eol
    got = ledger_events(blob)
    rec["appended"] = [next(csv.reader([ln.decode("utf-8").rstrip("\r")]))[0] for ln in appends]
    diff = sorted(set(got) ^ set(m_events)) + sorted({e for e in got if got.count(e) > 1})
    if diff or len(got) != len(m_events):
        raise MStop("LEDGER_EVENTS_MISMATCH", diff, "the ledger's events are not the M table's")
    rec["rows"] = len(got)
    return blob, rec


# ================================================================================================ star set
def _int(v):
    return int(float(v)) if v not in (None, "") else None


def _float(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def new_star_row(columns, *, subfield: str, author_id: str, name: str, school: str, arrival: int, aage,
                 rank_pass, restake: dict) -> dict:
    """A new star's star_set row in the frozen schema (build_u4_aug's mapping of the restake row);
    academic_age = the admitting rank's aage (restake_r1 already STOPs when own and C disagree)."""
    if aage in (None, ""):
        raise MStop("NEW_STAR_AGE_MISSING", [author_id])
    if rank_pass not in ("own", "C"):
        raise MStop("NEW_STAR_RANK_PASS", [author_id], f"rank_pass {rank_pass!r}")
    cell = (restake or {}).get("after_cell") or ""
    vals = {"author_id": author_id, "name": name or None, "dept": f"{school}_econ", "arrival": int(arrival),
            "subfield": subfield, "age_bin": cell.split("|")[1] if "|" in cell else None,
            "academic_age": int(aage), "stock": _int((restake or {}).get("after_stock")),
            "percentile": _float((restake or {}).get("after_pct")),
            "cell_n": _int((restake or {}).get("after_cell_n")),
            "is_star_1pct": True, "is_star_5pct": True, "age_eligible": True, "is_foreign_poach": True}
    return {c: vals.get(c) for c in columns}


#: restake_r1's tolerance between a signed pct_own and the rank's own value (a larger gap is reported, not used)
SIGNED_PCT_TOL = 5e-5


def signed_percentiles(*, flips_rows: list[dict], add_rows: list[dict], rank_row) -> tuple:
    """W2-1 (2026-10-16; N11 + F17): the M star set's percentile is the admitting pass's signed
    value for every M econ star. Returns (pct, rec): pct(author_id) -> float, rec filled as pct is called.
    - a star the signed lists do not make an M econ star (no econ KEEP flips row, no econ ACCEPT add-list row) is
      STARSET_UNSIGNED;
    - admitted on the own-field pass (the rank tables' rank_pass 'own') with a signed pct_own: float() of that 4-dp
      string (flips_r1.json for KEEP, add_list_r1.json for ACCEPT) - the exact value gaps_zenou compares at 1e-9;
      a gap to the rank's after_pct beyond SIGNED_PCT_TOL is reported (signed_vs_rank_differs), never used;
    - admitted on pass C (the signed lists hold no pass-C value), or on the own pass with an empty signed value:
      the admitting rank's after_pct rounded to the lists' 4 dp, reported by id.
    rank_row(author_id) -> {rank_pass, after_pct} (verdict_source.Source.row on the M rank tables)."""
    keep = {r["person_id"]: r for r in flips_rows if r.get("field") == "econ" and r.get("verdict") == "KEEP"}
    acc = {r["person_id"]: r for r in add_rows if r.get("field") == "econ" and r.get("verdict") == "ACCEPT"}
    rec = {"rule": "W2-1: signed admitting-pass value (flips_r1 KEEP / add_list_r1 ACCEPT pct_own; pass C: the "
                   "admitting rank at 4 dp)", "from_signed": [], "from_rank_pass_c": [],
           "own_without_signed_value": [], "signed_vs_rank_differs": []}

    def note(key, aid):
        rec[key] = sorted(set(rec[key]) | {aid})

    def pct(aid: str) -> float:
        s = keep.get(aid) or acc.get(aid)
        if s is None:
            raise MStop("STARSET_UNSIGNED", [aid], "an M star with no econ KEEP flips row and no econ ACCEPT add-list row")
        rk = rank_row(aid)
        rank_pct = _float(rk.get("after_pct"))
        signed = str(s.get("pct_own") or "").strip()
        if rk.get("rank_pass") == "own" and signed:
            v = float(signed)
            if rank_pct is not None and abs(v - rank_pct) > SIGNED_PCT_TOL:
                note("signed_vs_rank_differs", aid)
            note("from_signed", aid)
            return v
        if rk.get("rank_pass") not in ("own", "C"):
            raise MStop("STARSET_RANK_PASS", [aid], f"rank_pass {rk.get('rank_pass')!r}")
        if rank_pct is None:
            raise MStop("STARSET_RANK_PCT_MISSING", [aid])
        note("from_rank_pass_c" if rk.get("rank_pass") == "C" else "own_without_signed_value", aid)
        return round(rank_pct, 4)

    return pct, rec


def _first_pub(r: dict):
    """The first-publication year the union clone reads off a star-set row (star_first = arrival - 1 -
    academic_age, 00_build_frame_econ920_cal.py:368); None when either is missing."""
    a, g = r.get("arrival"), r.get("academic_age")
    return int(a) - 1 - int(g) if a is not None and g is not None else None


def star_set_rows_m(rows: list[dict], *, corr_stars: dict, unstar: set, redates: dict[str, str],
                    new_stars: list[dict], rank_age: dict, event_stars, signed_pct=None) -> tuple[list[dict], dict]:
    """The frozen u4_aug star set for this run: DROP stars' rows removed (they become ordinary
    colleagues), corrected stars re-keyed (as October), a re-dated star's arrival moved with its
    academic_age (arrival - 1 - academic_age = the first-publication year stays, h2), new stars added.
    Existing rows keep their frozen ages; every difference to the rank's aage is reported (ids).
    A new star can already hold a frozen row: the 277-row set is the U4 candidate table, one row per author_id,
    165 of them not October events. The union clone reads a row only as an is_star_1pct flag (the ex_star alias
    set) and as star_first, which it looks up for an event's own star alone, so October never read such a row's
    arrival or age. That row is REPLACED in place by the new event's row, built exactly as for an absent new star
    (the event's school and arrival, the admitting rank's aage - R1P3-16's rule for new events - and all four
    flags True: new stars are stars everywhere); the frozen row's school, arrival, age, flags and both
    first-publication years are reported ('replaced'). The one case the rules do not settle STOPs
    (STARSET_NEW_PRESENT): one star with two events in this run - a new star that is also in event_stars (the
    stars of the run's other events) or has two new events, or a frozen set with two rows for it - since the
    star set, the clone's star_first and provenance_m hold one row per star.
    signed_pct (W2-1, M only): the percentile of every event star of the run (event_stars and the new stars) =
    signed_pct(author_id); the other candidate rows keep their frozen percentile; None (the October plan) keeps
    them all."""
    rows = [dict(r) for r in rows]
    columns = list(rows[0]) if rows else []
    subs = {r.get("subfield") for r in rows if r.get("subfield")}
    if new_stars and len(subs) != 1:
        raise MStop("STARSET_SUBFIELD", [], f"frozen star set carries subfield codes {sorted(subs)}")
    rec: dict = {"rows_in": len(rows), "removed": sorted(r["author_id"] for r in rows if r["author_id"] in unstar),
                 "rekeyed": [], "redated": [], "added": [], "replaced": []}
    rows = [r for r in rows if r["author_id"] not in unstar]
    for old, new in sorted(corr_stars.items()):
        hit = [r for r in rows if r["author_id"] == old]
        if len(hit) != 1 or any(r["author_id"] == new for r in rows):
            raise MStop("STARSET_CORRECTION", [old, new])
        hit[0]["author_id"] = new
        rec["rekeyed"].append({"old": old, "new": new})
    for old_e, new_e in sorted(redates.items()):
        star, old_y = old_e.split(":")
        new_y = int(new_e.split(":")[1])
        hit = [r for r in rows if r["author_id"] == star]
        if len(hit) != 1:
            raise MStop("STARSET_REDATE_HITS", [star])
        r = hit[0]
        if int(r["arrival"]) != int(old_y):
            raise MStop("STARSET_ARRIVAL", [old_e], f"frozen arrival {r['arrival']}")
        if r.get("academic_age") is None:
            raise MStop("STARSET_AGE_MISSING", [star])
        first = int(r["arrival"]) - 1 - int(r["academic_age"])
        r["academic_age"] = int(r["academic_age"]) + (new_y - int(old_y))
        r["arrival"] = new_y
        assert r["arrival"] - 1 - r["academic_age"] == first
        rec["redated"].append({"star": star, "old_arrival": int(old_y), "new_arrival": new_y,
                               "academic_age": r["academic_age"], "first_pub": first})
    diffs = []
    for r in rows:
        ra = rank_age.get(r["author_id"])
        if ra is not None and r.get("academic_age") is not None and int(ra) != int(r["academic_age"]):
            diffs.append({"star": r["author_id"], "frozen": int(r["academic_age"]), "rank": int(ra)})
    event_stars = set(event_stars)
    for n in new_stars:
        aid = n["author_id"]
        if aid in event_stars or aid in rec["added"]:
            raise MStop("STARSET_NEW_PRESENT", [aid], "one star with two events in this run: the star set holds one "
                                                      "row (one first-publication year) per star")
        row = new_star_row(columns, subfield=next(iter(subs)) if subs else None,
                           author_id=aid, name=n.get("name", ""), school=n["school"],
                           arrival=n["arrival"], aage=n.get("aage"), rank_pass=n.get("rank_pass"),
                           restake=n.get("restake") or {})
        hit = [i for i, r in enumerate(rows) if r["author_id"] == aid]
        if len(hit) > 1:
            raise MStop("STARSET_NEW_PRESENT", [aid], f"the frozen star set holds {len(hit)} rows for this star")
        if hit:
            old = rows[hit[0]]
            if "name" in row and not row["name"]:
                row["name"] = old.get("name")
            rows[hit[0]] = row
            rec["replaced"].append({
                "star": aid, "event": f"{aid}:{row['arrival']}",
                "frozen": {**{k: old.get(k) for k in ("dept", "arrival", "academic_age", "is_star_1pct",
                                                      "is_star_5pct", "age_eligible", "is_foreign_poach")},
                           "first_pub": _first_pub(old)},
                "new": {"dept": row["dept"], "arrival": row["arrival"], "academic_age": row["academic_age"],
                        "first_pub": _first_pub(row)},
                "same_school_and_arrival": (old.get("dept"), old.get("arrival")) == (row["dept"], row["arrival"]),
                "first_pub_differs": _first_pub(old) != _first_pub(row)})
        else:
            rows.append(row)
        rec["added"].append(aid)
    rec["age_differs_from_rank"] = diffs
    if signed_pct is not None:
        changed, frozen = [], []
        stars = event_stars | set(rec["added"])
        for r in rows:
            if r["author_id"] not in stars:          # a U4 candidate row, no event of this run: October's value
                frozen.append(r["author_id"])
                continue
            v = signed_pct(r["author_id"])
            if r.get("percentile") != v:
                changed.append(r["author_id"])
            r["percentile"] = v
        rec["percentile"] = {"rule": "W2-1 signed admitting-pass value, for the run's event stars",
                             "changed": changed, "frozen_non_event": sorted(frozen)}
    rec["rows_out"] = len(rows)
    return rows, rec


def star_set_m(src: pathlib.Path, out: pathlib.Path, **kw) -> dict:
    """star_set_rows_m on the frozen parquet, written in the frozen schema (October's write call)."""
    import pyarrow as pa                                                 # noqa: PLC0415
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    t = pq.read_table(src)
    rows, rec = star_set_rows_m(t.to_pylist(), **kw)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=t.schema), out)
    rec.update({"source": str(src), "source_sha256": sha(src), "out_sha256": sha(out)})
    return rec


# ================================================================================================ frames
def provenance_m(age_bytes: bytes, regen: dict[str, dict]) -> bytes:
    """October's provenance table (the age table + one row per regenerated event); no star twice."""
    extra = {e: {"name": m.get("name") or "", "school": m.get("school") or "", "source": PROVENANCE_SOURCE[m["kind"]]}
             for e, m in regen.items()}
    blob = L.provenance_table(age_bytes, extra)
    rows = list(csv.DictReader(io.StringIO(blob.decode("utf-8"))))
    stars = [r["author_id"] for r in rows]
    dup = sorted({s for s in stars if stars.count(s) > 1})
    if dup:
        raise MStop("PROVENANCE_DUPLICATE_STAR", dup)
    evs = {f"{r['author_id']}:{int(r['arrival'])}" for r in rows}
    missing = sorted(set(regen) - evs)
    if missing:
        raise MStop("PROVENANCE_MISSING_EVENT", missing)
    return blob


def split_net1(frame: pathlib.Path, *, regen: set[str], fnfix: set[str],
               out_dir: pathlib.Path) -> dict[str, tuple[pathlib.Path, int]]:
    """net1 -> its builders' row groups, {part: (out_dir/net1_<part>_rows.csv, rows)} for FREEZE_PARTS, each
    byte-preserving with the header: 'regenerated' = the REGEN events (this run's prodlib), 'fnfix' = the other
    events of the frozen age table (the 2026-08-15 prodlib run; 01_merge_inputs.py asserts that every one of its
    rows is an age-table event), 'july' = the rest (the July rows, byte-preserved since 07-22)."""
    header, lines, trailing = L.read_frame_lines(frame)
    rows: dict[str, list[bytes]] = {k: [] for k in FREEZE_PARTS}
    for ln in lines:
        e = L.cells_of(ln)[3]
        rows["regenerated" if e in regen else "fnfix" if e in fnfix else "july"].append(ln)
    out = {}
    for k in FREEZE_PARTS:
        p = pathlib.Path(out_dir) / f"net1_{k}_rows.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\n".join([header] + rows[k]) + (b"\n" if trailing else b""))
        out[k] = (p, len(rows[k]))
    return out


def fnfix_events(v2: pathlib.Path) -> set[str]:
    """The events the 2026-08-15 prodlib run built: the frozen age table (new_events_econ.csv)."""
    return set(age_table_events(pathlib.Path(v2) / NEW_EVENTS_REL))


def _glob_files(g: str) -> int:
    import glob as _glob                                                 # noqa: PLC0415
    return sum(1 for _ in _glob.iglob(g, recursive=True))


def fnfix_graph(v2: pathlib.Path, *, rebase=None) -> tuple[nf.Graph, dict]:
    """The graph that built the fn-fix events' network rows: the frozen 2026-08-15 prodlib config
    (FNFIX_CONFIG_REL) - its snapshot copy (the 11-school edges and works plus the overlay of the 07-24
    rebuild), its person map (the U2 map plus that rebuild's 'P_<author id>' singletons for incumbents the
    U2 map lacks) and the fnfix supplement - with the recorded roots (config/paths.yaml) moved onto this
    host (run_cal_frames_chemmath.rebase_recorded_roots). Every graph input must exist and the supplement
    must be the pinned frozen file (econ920_lib.LEGACY_PINS). Returns (graph, record)."""
    p = pathlib.Path(v2) / FNFIX_CONFIG_REL
    if not p.is_file():
        raise MStop("FNFIX_GRAPH_MISSING", [], f"no frozen 08-15 econ prodlib config at {p}")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    if rebase is None:
        import run_cal_frames_chemmath as rcf                            # noqa: PLC0415  (cal2026-10, on sys.path via L)
        rebase = rcf.rebase_recorded_roots
    cfg, moved = rebase(cfg)
    g = nf.graph_from_prodlib_config(cfg)
    missing = [x for x in (g.edges_glob, g.works_glob) if _glob_files(x) == 0]
    missing += [x for x in (g.supplement_jsonl, g.person_map_parquet) if x and not pathlib.Path(x).is_file()]
    if missing:
        raise MStop("FNFIX_GRAPH_MISSING", [], f"inputs of the 08-15 econ prodlib graph: {missing}")
    if g.supplement_jsonl and sha(pathlib.Path(g.supplement_jsonl)) != L.LEGACY_PINS[SUP_FNFIX_REL]:
        raise MStop("FNFIX_GRAPH_PIN", [], f"{g.supplement_jsonl} is not the pinned fnfix supplement")
    return g, {"config": str(p), "config_sha256": sha(p), "roots_rebased": sorted(moved),
               "edge_files": _glob_files(g.edges_glob), "work_files": _glob_files(g.works_glob),
               "graph": dataclasses.asdict(g)}


def freeze_graphs(ctx, *, need_fnfix: bool) -> tuple[dict[str, nf.Graph | None], dict]:
    """V3-NET's graph for each net1 row group = the graph its builder used (the ruling-pending default on the
    author sheet, network_freeze.py): 'july' = the 11-school edges / works of the rendered econ prodlib config
    + the shadow's concatenated econ supplement + the U2 person map; 'fnfix' = the 2026-08-15 run's own graph
    (fnfix_graph; None when net1 holds no fn-fix row); 'regenerated' = the rendered prodlib config."""
    g_july = nf.Graph(str(ctx.prod_cfg["snapshot"]["edges_glob"]), str(ctx.prod_cfg["snapshot"]["works_glob"]),
                      str(ctx.sh.path(SUP_FNFIX_REL)), str(L.person_map_path()))
    g_fnfix, rec = fnfix_graph(ctx.v2) if need_fnfix else (None, None)
    return ({"july": g_july, "fnfix": g_fnfix, "regenerated": nf.graph_from_prodlib_config(ctx.prod_cfg)},
            {"july": dataclasses.asdict(g_july), "fnfix": rec})


def join_frames(parts: list[pathlib.Path], out: pathlib.Path) -> None:
    header = None
    lines: list[bytes] = []
    trailing = True
    for p in parts:
        h, ls, t = L.read_frame_lines(p)
        if header is None:
            header, trailing = h, t
        assert h == header, "frame parts with different headers"
        lines += ls
    out.write_bytes(b"\n".join([header] + lines) + (b"\n" if trailing else b""))


def r1_patch_persons(path) -> set[str]:
    """The author ids of the R1 works-by-author supplement (patch_assemble's jsonl); none when absent."""
    if path is None or not pathlib.Path(path).is_file():
        return set()
    return {json.loads(ln)["author_id"] for ln in pathlib.Path(path).read_text(encoding="utf-8").splitlines() if ln}


def rows_proof_m(frozen_pre_y, union_out, regen_events: set[str], allowances: dict | None,
                 work: pathlib.Path, r1_persons=None, need_outcomes=None, m_rules: bool = True) -> dict:
    """econ920_lib.union_rows_proof(..., REGEN) on the UNFIXED frame. V3-NET's dropped relations
    (proof_allowances) are set aside from the reference first: they may come back only as rebuilt
    dept_only rows (no frozen source), never as network/both rows. The M classes (explain_dept_rows) close
    the proof only when m_rules (config M); B0 keeps October's verdict."""
    ref = pathlib.Path(frozen_pre_y)
    removed = set((allowances or {}).get("removed") or ())
    aside = 0
    if removed:
        header, lines, trailing = L.read_frame_lines(ref)
        keep = []
        for ln in lines:
            c = L.cells_of(ln)
            if (c[0], c[3]) in removed or (L.pid_form(c[0]), c[3]) in removed:
                aside += 1
                continue
            keep.append(ln)
        work.mkdir(parents=True, exist_ok=True)
        ref = work / "frozen_pre_y_minus_network_freeze.csv"
        ref.write_bytes(b"\n".join([header] + keep) + (b"\n" if trailing else b""))
    proof = L.union_rows_proof(ref, pathlib.Path(union_out), set(regen_events))
    proof["allowances"] = {"relations_removed_by_network_freeze": len(removed), "frozen_rows_set_aside": aside}
    proof["m_explained"] = explain_dept_rows(ref, pathlib.Path(union_out), set(regen_events), set(r1_persons or ()),
                                             set(need_outcomes or ()))
    c = proof["counts"]
    if (m_rules and not proof["closed"] and not c.get("OTHER_DIFFERENCE") and not c.get("network_row_without_frozen_source")
            and proof["m_explained"]["unexplained"] == 0):
        proof["closed"] = True
        proof["closed_by"] = ("M: every changed rebuilt dept_only row differs only in ex_star outcomes (F11), "
                              "flips between empty and 0 with the M rosters, or takes its outcomes from the R1 patch")
    return proof


#: outcomes that drop papers written with a star: in M the star set holds the new stars too (F11), so these
#: cells of an October event's rebuilt dept_only row can change while the row counts the same papers
EX_STAR_COLS = ("pub_count_ex_star", "fwci_frac_ex_star", "fwci_mean_ex_star")
#: a row's outcome cells: empty = the person-year is outside employment, 0 = employed with no papers; the M
#: rosters move some person-years across that line, so all changed cells flip together between empty and 0
OUTCOME_COLS = ("fwci_frac", "pub_count", "fwci_frac_ex_star", "pub_count_ex_star", "fwci_mean", "fwci_mean_ex_star")


def _is_zero(v: str) -> bool:
    try:
        return float(v) == 0.0
    except ValueError:
        return False


#: the clone's two fill rows (00_build_frame_econ920_cal.py, step 5): employed without papers = the four sums
#: and counts 0 and both means empty; outside employment = all six empty
MEAN_COLS = ("fwci_mean", "fwci_mean_ex_star")


def _fill_kind(cells: list[str]) -> str | None:
    """'zero' / 'empty' when a row's six outcome cells are one of the clone's two fill rows, else None."""
    vals = {n: cells[L.FRAME_COLS.index(n)] for n in OUTCOME_COLS}
    if all(v == "" for v in vals.values()):
        return "empty"
    if all(vals[n] == "" for n in MEAN_COLS) and all(_is_zero(vals[n]) for n in OUTCOME_COLS if n not in MEAN_COLS):
        return "zero"
    return None


def _fill_flip(fc: list[str], c: list[str], diff: list[int]) -> str | None:
    """'roster_fill_empty_to_zero' / 'roster_fill_zero_to_empty' when only outcome cells changed and the row
    switched between the clone's two whole fill rows; else None (a partial change is not a roster fill)."""
    names = [L.FRAME_COLS[i] if i < 16 else "channel" for i in diff]
    if not diff or any(n not in OUTCOME_COLS for n in names):
        return None
    pair = (_fill_kind(fc), _fill_kind(c))
    return {("empty", "zero"): "roster_fill_empty_to_zero", ("zero", "empty"): "roster_fill_zero_to_empty"}.get(pair)


def _counts_ok(c: list[str]) -> bool:
    """pub_count and pub_count_ex_star are empty or whole non-negative numbers, and ex_star <= the count."""
    def whole(v):
        try:
            f = float(v)
        except ValueError:
            return None
        return f if math.isfinite(f) and f >= 0 and f == int(f) else None
    pc, pce = c[L.FRAME_COLS.index("pub_count")], c[L.FRAME_COLS.index("pub_count_ex_star")]
    a, b = (whole(pc) if pc != "" else ""), (whole(pce) if pce != "" else "")
    if a is None or b is None:
        return False
    return a == "" or b == "" or b <= a


def explain_dept_rows(frozen: pathlib.Path, union_out: pathlib.Path, regen: set[str], r1_persons=frozenset(),
                      need_outcomes=frozenset()) -> dict:
    """Every rebuilt dept_only row of a kept event that differs from its frozen row. Explained: (1) the row
    switched between the clone's two whole fill rows (the M rosters); (2) every changed cell is an outcome cell
    of a person outside U5's output table (the clone's need_outcomes) whom the R1 patch now supplies; (3) every
    changed cell is an ex_star outcome, or fwci_frac / fwci_mean within 8 ULP (the union rung's own noise, c1a),
    with whole non-negative counts and pub_count_ex_star <= pub_count. Anything else is unexplained. Returns
    counts and the first unexplained rows (ids and numbers)."""
    fz = L.frame_index(frozen)
    _, lines, _ = L.read_frame_lines(union_out)
    ex_only, r1_rows, bad = 0, 0, []
    flips = collections.Counter()
    for ln in lines:
        c = L.cells_of(ln)
        if c[3] in regen or c[16] != "dept_only":
            continue
        src = fz.get((c[0], c[3], c[1]))
        if src is None:
            continue
        fc = L.cells_of(src)
        if fc == c:
            continue
        diff = [i for i in range(17) if fc[i] != c[i]]
        names = [L.FRAME_COLS[i] if i < 16 else "channel" for i in diff]
        flip = _fill_flip(fc, c, diff)
        if flip:
            flips[flip] += 1
            continue
        # the clone takes an out-of-U5 person's outcomes from the API patch first, the U1 edges only for people
        # the patch lacks (00_build_frame_econ920_cal.py, v9); October had no patch rows for some people the R1
        # fetch now supplies, so their outcome cells move from the edges fallback to the patch
        bare = c[0].removeprefix("P_")
        if bare in r1_persons and bare in need_outcomes and all(n in OUTCOME_COLS for n in names):
            r1_rows += 1
            continue

        def ok(i):
            n = L.FRAME_COLS[i] if i < 16 else "channel"
            if n in EX_STAR_COLS:
                return True
            return n in ("fwci_frac", "fwci_mean") and fc[i] and c[i] and L.fs08.ulps(float(fc[i]), float(c[i])) <= 8
        if all(ok(i) for i in diff) and _counts_ok(c):
            ex_only += 1
        else:
            bad.append({"key": [c[0], c[3], c[1]], "cols": names,
                        "frozen": {n: fc[i] for n, i in zip(names, diff)}, "new": {n: c[i] for n, i in zip(names, diff)}})
    return {"ex_star_only": ex_only, "r1_patch_replaces_edges_fallback": r1_rows,
            "roster_fill_empty_to_zero": flips["roster_fill_empty_to_zero"],
            "roster_fill_zero_to_empty": flips["roster_fill_zero_to_empty"],
            "unexplained": len(bad), "unexplained_rows": bad[:20]}


def star_person_forms(star_ids, aliases: dict[str, list[str]], person_map) -> set[str]:
    """Every frame id form of the given stars: 'P_' + author id of the star and of its aliases, the U2
    person id of each of those author ids, and 'P_' + every sibling author id the person map folds to
    that person (the alias closure: the union's dept channel writes a roster fragment as 'P_' + its own
    author id - stage.build_exclusion expands fragments the same way; M review #0)."""
    ids = {a for s in star_ids for a in [s, *aliases.get(s, ())]}
    forms = {"P_" + a for a in ids}
    if ids and person_map is not None:
        import duckdb                                                    # noqa: PLC0415
        pm = pathlib.Path(person_map).as_posix()
        con = duckdb.connect()
        try:
            con.execute("CREATE TABLE ids_t (author_id VARCHAR)")
            con.executemany("INSERT INTO ids_t VALUES (?)", [(a,) for a in sorted(ids)])
            for person, sibling in con.execute(
                    f"SELECT DISTINCT p.person_id, q.author_id FROM ids_t JOIN read_parquet('{pm}') p USING (author_id) "
                    f"JOIN read_parquet('{pm}') q ON q.person_id = p.person_id").fetchall():
                if person:
                    forms.add(person)
                if sibling:
                    forms.add("P_" + sibling)
        finally:
            con.close()
    return forms


def assert_no_star_incumbents(frame, forms: set[str]) -> None:
    _h, lines, _t = L.read_frame_lines(pathlib.Path(frame))
    bad = sorted({L.pid_form(L.cells_of(ln)[0]) for ln in lines if L.pid_form(L.cells_of(ln)[0]) in forms})
    if bad:
        raise MStop("INCUMBENT_STAR_SURVIVOR", bad, "a star of this run is still an incumbent")


def drop_incumbent_stars(pre_y, rel, forms: set[str], out_dir) -> dict:
    """Remove every row (any channel) and relationships line whose incumbent is one of `forms`; counted
    under the cause 'incumbent_is_star_r1'. No form = nothing read or written (October's path)."""
    pre_y, rel = pathlib.Path(pre_y), pathlib.Path(rel)
    base = {"cause": "incumbent_is_star_r1", "forms": len(forms)}
    if not forms:
        return {**base, "rows_dropped": 0, "relations_dropped": 0, "persons": [], "events": [],
                "rows_dropped_by_channel": {}, "output": {"pre_y": str(pre_y), "relationships": str(rel)}}
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    header, lines, trailing = L.read_frame_lines(pre_y)
    keep, by_ch, rels = [], collections.Counter(), set()
    for ln in lines:
        c = L.cells_of(ln)
        if L.pid_form(c[0]) in forms:
            by_ch[c[16]] += 1
            rels.add((L.pid_form(c[0]), c[3]))
            continue
        keep.append(ln)
    p_out = out_dir / "pre_y_minus_star_incumbents.csv"
    p_out.write_bytes(b"\n".join([header] + keep) + (b"\n" if trailing else b""))
    raw = rel.read_bytes().split(b"\n")
    hdr = raw[0].decode("utf-8").rstrip("\r").split(",")
    ip, ie = hdr.index("pid"), hdr.index("event_id")
    kept_rel, n_rel = [raw[0]], 0
    for ln in raw[1:]:
        if not ln:
            kept_rel.append(ln)
            continue
        c = ln.decode("utf-8").rstrip("\r").split(",")
        if L.pid_form(c[ip]) in forms:
            n_rel += 1
            continue
        kept_rel.append(ln)
    r_out = out_dir / "relationships.csv"
    r_out.write_bytes(b"\n".join(kept_rel))
    assert_no_star_incumbents(p_out, forms)
    return {**base, "rows_dropped": sum(by_ch.values()), "rows_dropped_by_channel": dict(by_ch),
            "relations_dropped": len(rels), "relationships_lines_dropped": n_rel,
            "persons": sorted({p for p, _e in rels}), "events": sorted({e for _p, e in rels}),
            "output": {"pre_y": str(p_out), "sha256": sha(p_out), "rows": len(keep),
                       "relationships": str(r_out), "relationships_sha256": sha(r_out)}}


def read_pairs(p) -> frozenset:
    with open(p, newline="", encoding="utf-8") as fh:
        return frozenset((r["person_id"], r["work_id"]) for r in csv.DictReader(fh))


PATCH_ASSEMBLE_REPORT = "report_patch_assemble.json"


def fetch_round(cfg, patch_r1) -> int:
    """1 + the number of R1 fetch rounds already assembled, from the run config's fetched tags (sections.patch.tags,
    the list the patch_assemble stage reads), cross-checked against patch_assemble's report beside the supplement:
    no tag = round 1, a tag = round 2 - even when every fetched profile came back empty and the supplement is 0
    bytes (M review #6; before, an empty supplement meant round 1 and the build looped on AGG_MISSING). B0
    (patch_r1 None) is round 1."""
    if patch_r1 is None:
        return 1
    tags = list(((cfg.raw.get("sections") or {}).get("patch") or {}).get("tags") or [])
    data = pathlib.Path(patch_r1).read_bytes()
    rp = pathlib.Path(patch_r1).parent / PATCH_ASSEMBLE_REPORT
    if not rp.is_file():
        raise MStop("PATCH_ROUND_MISMATCH", [], f"no {PATCH_ASSEMBLE_REPORT} beside the R1 supplement")
    rep = _json(rp)
    want = "assembled" if tags else "no tags"
    if rep.get("status") != want or list(rep.get("tags") or []) != tags:
        raise MStop("PATCH_ROUND_MISMATCH", [], f"patch_assemble status {rep.get('status')!r} tags {rep.get('tags')!r}, "
                                                f"config tags {tags!r}")
    if data.strip() and not tags:
        raise MStop("PATCH_ROUND_MISMATCH", [], "a non-empty R1 supplement with no fetched tag in the run config")
    return 2 if tags else 1


P1_UNIFIED_REL = f"{L.ECON}/data/analysis_frame_econ920_unified_fullsnap_2026-08-13.csv"
Y_COLS = ("fwci_frac", "fwci_frac_ex_star", "fwci_mean", "fwci_mean_ex_star")


def after_fetch_check(ch: dict, after_fetch: dict | None, pre_y, prodlib_events: set[str]) -> tuple[bool, dict]:
    """After the one authorised fetch round (agg_missing code AGG_MISSING_AFTER_FETCH) the old-event rows
    of the persons still without an outcome source stay y = NA and the build goes on. October's 04_rebuild_y.py
    (unedited) still writes both frames and then exits 2 on exactly those rows (C-PC 'agg_missing', once per
    variant). Its written unified frame is accepted only when every reason for the exit is one of them:
      a. old_value_reproduction_anchor.hard_fail_cells == 0;   b. G_D_hand_check_10py.pass;
      c. C_PC_structural_anchor.bad_rows == 2 x after_fetch.rows (unified + denomonly: any pc_mismatch,
         old_*_but_agg_present or other person's agg_missing row breaks the equality);
      d. a rescan of the written unified frame: the pre-y frame's row count, and the authorised persons'
         old-event rows with publications number exactly after_fetch.rows and carry four NA y values.
    Returns (ok, record); round 1 (after_fetch None) is never ok (M review #5)."""
    rec: dict = {"rule": "R1P3-25: AGG_MISSING_AFTER_FETCH old-event rows stay NA", "checks": {}}
    if not after_fetch:
        rec["why"] = "no AGG_MISSING_AFTER_FETCH in this run (round 1, or nobody missing)"
        return False, rec
    persons, rows = set(after_fetch.get("persons") or ()), int(after_fetch.get("rows") or 0)
    rec.update({"persons": sorted(persons), "rows": rows})
    p1 = ch.get("p1_econ") or {}
    g_path = (p1.get("g_econ_rebuild") or {}).get("path")
    written = p1.get("unified_frame_written")
    if not (rows > 0 and g_path and pathlib.Path(g_path).is_file() and written and pathlib.Path(written).is_file()):
        rec["why"] = "no authorised rows, or 04 left no g_econ_rebuild.json / unified frame"
        return False, rec
    g = _json(g_path)
    c = rec["checks"]
    c["pass_false"] = g.get("PASS") is False
    c["a_repro_hard_fail_0"] = (g.get("old_value_reproduction_anchor") or {}).get("hard_fail_cells") == 0
    c["b_hand_check_pass"] = (g.get("G_D_hand_check_10py") or {}).get("pass") is True
    bad = (g.get("C_PC_structural_anchor") or {}).get("bad_rows")
    c["c_bad_rows_eq_2x_rows"] = bad == 2 * rows
    rec["bad_rows"] = bad
    n_pre = len(L.read_frame_lines(pathlib.Path(pre_y))[1])
    with open(written, newline="", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        hdr = next(rd)
        ix = {k: hdr.index(k) for k in ("incumbent_person_id", "event_id", "pub_count", *Y_COLS)}
        n_written, auth, auth_na = 0, 0, 0
        for r in rd:
            n_written += 1
            if (r[ix["incumbent_person_id"]] in persons and r[ix["event_id"]] not in prodlib_events
                    and r[ix["pub_count"]] not in ("", "0", "0.0")):
                auth += 1
                auth_na += all(r[ix[k]] == "" for k in Y_COLS)
    c["d_rows_eq_pre_y"] = n_written == n_pre
    c["d_authorised_rows_eq"] = auth == rows
    c["d_authorised_rows_all_na"] = auth_na == auth
    rec["rescan"] = {"rows_written": n_written, "rows_pre_y": n_pre, "authorised_rows": auth, "authorised_rows_na": auth_na}
    return all(c.values()), rec


# ================================================================================================ G-DOSE (3h)
def override_ruling(cfg_name: str) -> str:
    return M_OVERRIDE_RULING if cfg_name == "M" else OCTOBER_OVERRIDE_RULING


@contextlib.contextmanager
def ruling_installed(cfg_name: str):
    """run_econ920.OVERRIDE_RULING for the duration: M cites h4; B0 keeps October's string."""
    old = R.OVERRIDE_RULING
    R.OVERRIDE_RULING = override_ruling(cfg_name)
    try:
        yield
    finally:
        R.OVERRIDE_RULING = old


def gdose_policy(cfg) -> str:
    """The run config's G-DOSE ruling; no default (a missing ruling is a STOP)."""
    try:
        v = cfg.ruling("gdose_override")
    except (r1_config.ConfigStop, KeyError, LookupError):
        raise MStop("GDOSE_RULING_MISSING", [], "the run config carries no gdose_override ruling") from None
    if v != GDOSE_RULING_VALUE:
        raise MStop("GDOSE_RULING_UNKNOWN", [], f"gdose_override {v!r}")
    return v


def gdose_draw(old_frame, prov_events: set[str]) -> list[tuple[str, str]]:
    """The clone's draw, replicated as econ920_lib.predict_gdose_draw does it, as (pid, event) pairs."""
    import pandas as pd                                                  # noqa: PLC0415
    old = pd.read_csv(old_frame)
    old["pid"] = old.incumbent_person_id.map(lambda x: x.replace("P_", "", 1))
    g = old[["pid", "event_id", "dose_topic"]].drop_duplicates(["pid", "event_id"])
    g = g[~g.event_id.isin(prov_events)]
    g = g.sample(n=min(200, len(g)), random_state=42)
    return [(r.pid, r.event_id) for r in g.itertuples()]


@contextlib.contextmanager
def clone_g_row_capture():
    """Keep the union clone's FULL G_ROW list and the sets it was built from. Read-only: json.dump is wrapped
    for the block, and at the clone's own json.dump(report, ...) the frame whose global 'report' is the dumped
    dict is the clone's namespace. run_union's own wrapper (econ920_lib, used with the override) calls through
    this one. Yields {} until the clone dumps; then mism, need_outcomes (incumbents outside U5's output table),
    new_events (the clone's _NEW_EV), sample_both and W."""
    got: dict = {}
    real = json.dump

    def _dump(obj, fp, *a, **k):
        if not got and isinstance(obj, dict) and "G_DOSE" in obj and "G_ROW" in obj:
            f = sys._getframe(1)
            while f is not None and f.f_globals.get("report") is not obj:
                f = f.f_back
            if f is not None:
                g = f.f_globals
                got.update({"mism": list(g["mism"]) if "mism" in g else None,
                            "need_outcomes": set(g.get("need_outcomes") or ()),
                            "api_persons": set(g.get("api_pids") or ()),
                            "new_events": set(g.get("_NEW_EV") or ()),
                            "sample_both": list(g.get("sample_both") or ()), "W": g.get("W")})
        return real(obj, fp, *a, **k)

    json.dump = _dump
    try:
        yield got
    finally:
        json.dump = real


def _cell_num(v):
    """A finite number, else None (NA, NaN, text)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _cell(m, col, old, new) -> dict:
    ids = [str(x) for x in m[:2] if _GDOSE_ID.match(str(x))]
    year = m[2] if len(m) > 2 and isinstance(m[2], int) else _cell_num(m[2] if len(m) > 2 else None)
    return {"ids": ids, "year": int(year) if year is not None else None, "columns": [col] if col else [],
            "old": _cell_num(old), "new": _cell_num(new)}


def _block(entries: list) -> dict:
    """entries: [(relation key, cell)] -> counts, the ids in first-seen order, every cell."""
    ids = list(dict.fromkeys(i for _k, c in entries for i in c["ids"]))
    return {"n_cells": len(entries), "n_relations": len({k for k, _c in entries}), "ids": ids,
            "cells": [c for _k, c in entries]}


def classify_g_row(clone: dict | None, residuals: dict, reported) -> dict:
    """M's G_ROW rule over the clone's full mismatch list (clone_g_row_capture). Three classes are explained:
      outcome_new_event_outside_u5  a column 04_rebuild_y.py overwrites (L.Y_SWAPPED_BY_04) on a row of an event
                                    in the clone's _NEW_EV (the provenance table, which 04 reads too: Steps.chain),
                                    incumbent in the clone's need_outcomes (outside U5's output table). 04 writes
                                    these four cells from its own aggregate on every such row, whatever the frame
                                    held (04_rebuild_y.py:256-265, :312-313), so the clone's value reaches nothing
      dose_population_residual      dose_topic on a relation of October's residual table (run_econ920.residuals,
                                    as override_is_justified uses it), that difference (1e-12) on all its 2W+1 rows
      pub_count_source_new_event_outside_u5  pub_count / pub_count_ex_star on such a row of an incumbent the clone
                                    counts from the patch (its api_pids): the clone counts those papers from the
                                    patch, prodlib's rows from the snapshot; 04 keeps pub_count and notes the two
                                    sources differ (04_rebuild_y.py:320-321, October); an edges-fallback incumbent
                                    is 'other' (unexplained)
    Everything else is unexplained: NA mismatches, age_gap, a missing old row, outcome cells of other events or
    of incumbents inside U5's table. If the capture does not hold
    exactly the clone's own count (`reported`), nothing is explained."""
    mism = (clone or {}).get("mism")
    new_ev = set((clone or {}).get("new_events") or ())
    outside = set((clone or {}).get("need_outcomes") or ())
    api = set((clone or {}).get("api_persons") or ())
    w = (clone or {}).get("W")
    blocks: dict[str, list] = {k: [] for k in G_ROW_EXPLAINED + G_ROW_UNEXPLAINED}
    dose: dict = collections.defaultdict(list)
    for m in mism or []:
        key = (str(m[0]), str(m[1]))
        col = m[3] if len(m) > 3 and isinstance(m[3], str) else None
        if len(m) == 4 and col == "row_missing_in_old":
            blocks["row_missing_in_old"].append((key, _cell(m, None, None, None)))
        elif len(m) == 7 and m[4] == "NA_mismatch":
            blocks["na_mismatch"].append((key, _cell(m, col, m[5], m[6])))
        elif len(m) == 6 and col == "dose_topic":
            dose[key].append(m)
        elif len(m) == 6 and col == "age_gap":
            blocks["age_gap"].append((key, _cell(m, col, m[4], m[5])))
        elif len(m) == 6 and col in G_ROW_OUTCOME_COLS:
            cls = ("outcome_old_event" if key[1] not in new_ev else "outcome_inside_u5" if key[0] not in outside
                   else ("pub_count_source_new_event_outside_u5" if key[0] in api else "other")
                   if col not in L.Y_SWAPPED_BY_04 else "outcome_new_event_outside_u5")
            blocks[cls].append((key, _cell(m, col, m[4], m[5])))
        else:
            blocks["other"].append((key, _cell(m, col, m[-2] if len(m) >= 6 else None, m[-1] if len(m) >= 6 else None)))
    for key, rows in dose.items():
        r = residuals.get(key)
        try:
            arr = int(key[1].split(":")[1])
        except (IndexError, ValueError):
            arr = None
        years = sorted(int(m[2]) for m in rows)
        every_row = isinstance(w, int) and arr is not None and years == list(range(arr - w, arr + w + 1))
        same = r is not None and all(_cell_num(m[4]) is not None and _cell_num(m[5]) is not None
                                     and abs(abs(float(m[4]) - float(m[5])) - r) < 1e-12 for m in rows)
        cls = "dose_population_residual" if every_row and same else "dose_not_population_residual"
        blocks[cls] += [(key, _cell(m, "dose_topic", m[4], m[5])) for m in rows]
    n_rep = reported if isinstance(reported, int) and not isinstance(reported, bool) else None
    tied = (mism is not None and n_rep == len(mism)) or (n_rep == 0 and not mism)
    if not tied:                     # the capture is not the clone's own list: nothing counts as explained
        every = [e for k in G_ROW_EXPLAINED + G_ROW_UNEXPLAINED for e in blocks[k]]
        blocks = {k: [] for k in blocks}
        blocks["capture_not_tied_to_clone_count"] = every
    explained = {k: _block(blocks[k]) for k in G_ROW_EXPLAINED if blocks[k]}
    unexplained = {k: _block(blocks[k]) for k in G_ROW_UNEXPLAINED if blocks[k]}
    if not tied:
        n = max(n_rep or 0, len(mism or []), 1)
        unexplained["capture_not_tied_to_clone_count"] = {**_block(blocks["capture_not_tied_to_clone_count"]),
                                                          "n_cells": n}
    return {"rule": G_ROW_RULE, "captured": mism is not None, "n_reported": n_rep,
            "n_mismatches": None if mism is None else len(mism),
            "n_explained": sum(b["n_cells"] for b in explained.values()),
            "n_unexplained": sum(b["n_cells"] for b in unexplained.values()),
            "explained": explained, "unexplained": unexplained}


def gdose_verdict(cfg_name: str, prediction: dict, res: dict, clone: dict | None = None) -> tuple[bool, dict]:
    """run_econ920.override_is_justified under the run's ruling. B0: its verdict as it is. M: its G_ROW
    condition is replaced, in place, by M_G_ROW_CONDITION (0 UNEXPLAINED mismatches by classify_g_row over
    `clone`, the clone_g_row_capture of this run, and G_SUM ok); rec['g_row'] holds the classes."""
    with ruling_installed(cfg_name):
        ok, rec = R.override_is_justified(prediction, res)
    if cfg_name != "M":
        return ok, rec
    rep = res.get("report") or {}
    g_row = classify_g_row(clone, R.residuals(), (rep.get("G_ROW") or {}).get("mismatches"))
    m_ok = g_row["n_unexplained"] == 0 and (rep.get("G_SUM") or {}).get("ok") is True
    conds = {(M_G_ROW_CONDITION if k == OCTOBER_G_ROW_CONDITION else k): (m_ok if k == OCTOBER_G_ROW_CONDITION else v)
             for k, v in rec["conditions"].items()}
    conds.setdefault(M_G_ROW_CONDITION, m_ok)
    rec = {**rec, "conditions": conds, "g_row": g_row}
    return all(conds.values()), rec


def check_report_ids_only(obj) -> None:
    """ValueError unless every key is a GDOSE_KEYS key and every 'ids' entry is an OpenAlex/event id."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in GDOSE_KEYS:
                raise ValueError(f"key {k!r} is not allowed in a G-DOSE stage report")
            if k == "ids":
                bad = [i for i in v if not (isinstance(i, str) and _GDOSE_ID.match(i))]
                if bad:
                    raise ValueError(f"ids that are not OpenAlex/event ids: {bad[:5]}")
            check_report_ids_only(v)
    elif isinstance(obj, list):
        for v in obj:
            check_report_ids_only(v)


def gdose_body(cfg_name: str, code: str, prediction: dict, res: dict, rec: dict | None, override: bool) -> dict:
    pop = (R.REPORT.get("measurements") or {}).get("gdose_population") or {}
    rep = res.get("report") or {}
    gd, gr = rep.get("G_DOSE") or {}, rep.get("G_ROW") or {}
    failing = [w for w in res.get("drawn_residuals_gt_1e-9", []) if w.get("abs_diff", 0) > 0.01]
    ids = sorted({x for w in failing for x in (w["pid"], w["event_id"]) if _GDOSE_ID.match(str(x))})
    body = {"schema": "sar.r1.gdose_m.v1", "config": cfg_name, "code": code, "override": bool(override),
            "ruling": override_ruling(cfg_name),
            "population": {k: pop.get(k) for k in ("n", "share_exact_1e-9", "max_abs_diff", "n_gt_0.01", "n_gt_0.05")},
            "predicted": {"gate": prediction.get("predicted_gate"),
                          "max_abs_diff": prediction.get("predicted_max_abs_diff"),
                          "share_exact_1e-9": prediction.get("predicted_share_exact_1e-9"),
                          "drawn": prediction.get("drawn"),
                          "population_relations": prediction.get("population_relations")},
            "actual": {"G_DOSE": {k: gd.get(k) for k in ("n", "missing_side", "max_abs_diff", "share_exact_1e-9")},
                       "G_ROW": {k: gr.get(k) for k in ("sampled_both", "mismatches", "dose_tolerated_le_0.01",
                                                        "fill_divergence")},
                       "gate_overridden": bool(res.get("gate_overridden")), "exit": res.get("exit")},
            "conditions": {k: bool(v) for k, v in ((rec or {}).get("conditions") or {}).items()},
            "ids": ids, "n_ids": len(ids)}
    if rec and "g_row" in rec:                      # M only (gdose_verdict); B0's body is October's
        body["g_row"] = rec["g_row"]
    check_report_ids_only(body)
    return body


UNION_CHECK_KEYS = ("G_DOSE", "G_ROW", "G_ROW_fnfix_exstar_tolerated", "G_SUM", "frame", "GATE")


def log_union_checks(report_path: pathlib.Path) -> None:
    """Print the union clone's own checks (G_DOSE, G_ROW with its examples, G_SUM, the frame counts): the stop
    report keeps counts only, and a failed stage's work dir is not uploaded. Ids and numbers only."""
    p = pathlib.Path(report_path)
    if not p.is_file():
        log(f"no union report at {p}")
        return
    rep = json.loads(p.read_text(encoding="utf-8"))
    log("union checks " + json.dumps({k: rep.get(k) for k in UNION_CHECK_KEYS}, sort_keys=True, default=str))


def log_g_row(g_row: dict, limit: int = 60) -> None:
    """M's G_ROW classes on a stop: counts by class and the first `limit` unexplained cells (ids and numbers)."""
    counts = {k: b["n_cells"] for part in ("explained", "unexplained") for k, b in g_row.get(part, {}).items()}
    cells = [{"class": k, **c} for k, b in g_row.get("unexplained", {}).items() for c in b["cells"]][:limit]
    log("G_ROW classes " + json.dumps({"counts": counts, "n_reported": g_row.get("n_reported"),
                                       "n_mismatches": g_row.get("n_mismatches"), "unexplained_cells": cells},
                                      sort_keys=True))


def gdose_step(out, cfg_name: str, prediction: dict, res: dict, *, override: bool, clone: dict | None = None) -> dict:
    """The 3h measurement: write STAGE_OUT/report_gdose_m.json, or stop_report_gdose.json and STOP.
    With the override: gdose_verdict decides (False -> GDOSE_UNEXPLAINED; M with its own G_ROW condition,
    `clone` = the clone_g_row_capture of the run). Without it: a failed union gate is GDOSE_UNEXPLAINED
    when the draw was predicted to PASS, else UNION_GATE_FAILED."""
    rec = None
    if override:
        ok, rec = gdose_verdict(cfg_name, prediction, res, clone=clone)
        code = "OK_OVERRIDDEN" if ok else "GDOSE_UNEXPLAINED"
    elif "error" in res:
        code = "GDOSE_UNEXPLAINED" if prediction.get("predicted_gate") == "PASS" else "UNION_GATE_FAILED"
    else:
        code = "OK"
    body = gdose_body(cfg_name, code, prediction, res, rec, override)
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    stop = code not in ("OK", "OK_OVERRIDDEN")
    for stale in (GDOSE_REPORT, "stop_report_gdose.json"):
        (out / stale).unlink(missing_ok=True)
    target = out / ("stop_report_gdose.json" if stop else GDOSE_REPORT)
    target.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if stop:
        failed = [k for k, v in body["conditions"].items() if not v]
        if "g_row" in body:
            log_g_row(body["g_row"])
        raise MStop(code, body["ids"], f"failed conditions {failed}", name="gdose", written=True)
    return body


# ================================================================================================ regeneration
def exclusion_base(base: pathlib.Path, unstar: set[str], add_ids: set[str], out: pathlib.Path) -> dict:
    """The stars_excluded base for this run: the 08-28 list minus the DROP stars plus the aliases of the
    run's event stars (build_exclusion then adds every event star and their U2 fragments)."""
    import duckdb                                                        # noqa: PLC0415
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE drop_t (author_id VARCHAR)")
        con.execute("CREATE TABLE add_t (author_id VARCHAR)")
        if unstar:
            con.executemany("INSERT INTO drop_t VALUES (?)", [(a,) for a in sorted(unstar)])
        if add_ids:
            con.executemany("INSERT INTO add_t VALUES (?)", [(a,) for a in sorted(add_ids)])
        b = base.as_posix()
        removed = [t[0] for t in con.execute(f"SELECT author_id FROM read_parquet('{b}') WHERE author_id IN "
                                             f"(SELECT author_id FROM drop_t) ORDER BY 1").fetchall()]
        con.execute(f"COPY (SELECT author_id FROM read_parquet('{b}') WHERE author_id NOT IN "
                    f"(SELECT author_id FROM drop_t) UNION SELECT author_id FROM add_t ORDER BY author_id) "
                    f"TO '{out.as_posix()}' (FORMAT PARQUET)")
        n = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    finally:
        con.close()
    return {"base": str(base), "base_sha256": sha(base), "removed_drop_stars": removed,
            "added_aliases": sorted(add_ids), "rows": n, "sha256": sha(out)}


# ---- REGEN-AGE (option A, ruling 2026-10-17; j1a-10 STOP on (A5073781846, A5002563598:2017), clone 23 vs prodlib 17).
# October's prodlib config (configs/econ.json) builds age_gap with works_robust on both sides (prodlib.py:661-697),
# while the union clone (00_build_frame_econ920_cal.py:352-376) and the kept July / fn-fix rows use the 08-15 rule.
# In M the regenerated rows take the 08-15 rule too, so the whole frame has one age_gap rule. B0 keeps October's.
M_FIRST_PUB = {"star_first_pub": {"mode": "star_set_academic_age"}, "ego_first_pub": {"mode": "panel_then_wfp"}}
U3_PANEL_REL = "u3_panel_11school_2026-07-16/panel/data.parquet"          # the clone's U3P, under the derived root
PRODLIB_RESTAKE = "restake_econ_prodlib_m.csv"
AGE_RULE_0815 = ("08-15 rule: star first-publication year = arrival - 1 - academic_age of the star set; incumbent = "
                 "the U3 panel first_pub_year, then the work_first_pub fallback")
AGE_RULE_PIECE_A = "piece A (October cal2026-10 config): works_robust first-publication year on both sides"


def u3_panel_path() -> pathlib.Path:
    """The U3 panel file the union clone reads (U3P = <derived root>/u3_panel_11school_2026-07-16/panel/data.parquet)."""
    return _derived_root() / U3_PANEL_REL


def m_first_pub(pcfg: dict, panel: str) -> dict:
    """Switch a rendered prodlib config to the 08-15 first-publication rule (star_set_academic_age for the star,
    panel_then_wfp for the incumbent, which reads indept.panel_glob). The indept mode is left as rendered.
    Returns the old and new values for the build report."""
    if "indept" not in pcfg:
        raise MStop("PRODLIB_CONFIG_SHAPE", [], "the rendered prodlib config has no indept section")

    def now() -> dict:
        return {"star_first_pub": copy.deepcopy(pcfg.get("star_first_pub")),
                "ego_first_pub": copy.deepcopy(pcfg.get("ego_first_pub")),
                "indept.panel_glob": pcfg["indept"].get("panel_glob")}
    old = now()
    pcfg.update(copy.deepcopy(M_FIRST_PUB))
    pcfg["indept"]["panel_glob"] = str(panel)
    return {"rule": "REGEN-AGE option A: " + AGE_RULE_0815, "old": old, "new": now()}


def regen_star_ages(rows: list[dict], regen: dict[str, dict]) -> dict[str, int]:
    """author_id -> the M star set's academic_age for every regenerated star (new stars: the admitting rank's
    aage; an id-corrected star: its frozen age, re-keyed; a re-dated star: frozen age + the years moved, h2). The row's arrival must
    be the event's year, because prodlib reads arrival - 1 - academic_age. A missing row or age STOPs."""
    by = collections.defaultdict(list)
    for r in rows:
        by[r["author_id"]].append(r)
    ages, missing, moved = {}, [], []
    for e in sorted(regen):
        star, year = e.split(":")[0], int(e.split(":")[1])
        hit = by.get(star, [])
        if len(hit) != 1 or hit[0].get("academic_age") is None:
            missing.append(e)
        elif hit[0].get("arrival") is None or int(hit[0]["arrival"]) != year:
            moved.append(e)
        else:
            ages[star] = int(hit[0]["academic_age"])
    if missing:
        raise MStop("PRODLIB_STAR_AGE_MISSING", missing, "a regenerated event's star has no academic_age in the M star set")
    if moved:
        raise MStop("PRODLIB_STAR_ARRIVAL", moved, "the M star set's arrival is not the event's year")
    return ages


def _csv_cells(raw: bytes) -> tuple[list[str], bytes]:
    """One CSV line -> (cells, its line end). The line must write back to the same bytes (csv.writer, minimal
    quoting), so a rewritten line differs only in the cell we change."""
    body = raw.rstrip(b"\r\n")
    text = body.decode("utf-8")
    recs = list(csv.reader([text]))
    buf = io.StringIO()
    if len(recs) == 1:
        csv.writer(buf, lineterminator="").writerow(recs[0])
    if len(recs) != 1 or buf.getvalue() != text:
        raise MStop("PRODLIB_RESTAKE_ROUNDTRIP", [], f"a restake line does not write back byte for byte: {text[:60]!r}")
    return recs[0], raw[len(body):]


def prodlib_restake(blob: bytes, ages: dict[str, int], table_stars) -> tuple[bytes, dict]:
    """The restake table prodlib's star set is built from (stage.build_u4_aug reads it by column name), with aage =
    ages[author_id] for every regenerated star; every other byte as given. STOPs: a regenerated star without a row,
    or any event star of the econ table without an age (prodlib's star_set_academic_age mode needs one for each)."""
    lines = blob.splitlines(keepends=True)
    if not lines:
        raise MStop("PRODLIB_RESTAKE_SHAPE", [], "the restake table is empty")
    hdr, _end = _csv_cells(lines[0])
    if "author_id" not in hdr or "aage" not in hdr:
        raise MStop("PRODLIB_RESTAKE_SHAPE", [], f"header {hdr} has no author_id / aage")
    ia, ig = hdr.index("author_id"), hdr.index("aage")
    out, seen, changed, same = [lines[0]], {}, [], []
    for raw in lines[1:]:
        if not raw.strip():
            out.append(raw)
            continue
        c, end = _csv_cells(raw)
        aid = c[ia]
        if aid in seen:
            raise MStop("PRODLIB_RESTAKE_DUPLICATE", [aid])
        seen[aid] = c[ig]
        if aid in ages:
            new = str(int(ages[aid]))
            if c[ig] == new:
                same.append(aid)
            else:
                changed.append({"star": aid, "restake_aage": _int(c[ig]), "star_set_age": int(ages[aid])})
                c[ig] = new
                buf = io.StringIO()
                csv.writer(buf, lineterminator="").writerow(c)
                raw = buf.getvalue().encode("utf-8") + end
                seen[aid] = new
        out.append(raw)
    no_row = sorted(set(ages) - set(seen))
    if no_row:
        raise MStop("PRODLIB_RESTAKE_ROW_MISSING", no_row, "a regenerated star has no row in the restake table")
    no_age = sorted(a for a in set(table_stars) if seen.get(a) in (None, ""))
    if no_age:
        raise MStop("PRODLIB_RESTAKE_AGE_MISSING", no_age, "an event star has no age for prodlib's star set")
    rec = {"rule": "aage = the M star set's academic_age for every regenerated star (REGEN-AGE); other bytes as given",
           "changed": sorted(changed, key=lambda d: d["star"]), "unchanged": sorted(same)}
    return b"".join(out), rec


def prodlib_restake_m(ctx) -> tuple[dict, dict]:
    """M: the stage section prodlib's u4_aug is built from, its restake_csv replaced by the configured table with
    the M star set's ages for the regenerated stars (written under ctx.work)."""
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    rows = pq.read_table(ctx.star_set, columns=["author_id", "arrival", "academic_age"]).to_pylist()
    ages = regen_star_ages(rows, ctx.plan.regen)
    src = pathlib.Path(pa_stage.stage_value(ctx.stage_cfg, "restake_csv"))
    blob, rec = prodlib_restake(src.read_bytes(), ages, {e.split(":")[0] for e in ctx.plan.m_events})
    out = ctx.work / PRODLIB_RESTAKE
    out.write_bytes(blob)
    label = pa_stage.stage_value(ctx.stage_cfg, "restake_label")
    stage_cfg = {**ctx.stage_cfg, "restake_csv": out,
                 "restake_label": f"{label}; aage = the M star set's academic_age for the regenerated stars (REGEN-AGE)"}
    rec.update({"source": str(src), "source_sha256": sha(src), "out": str(out), "out_sha256": sha(out)})
    return stage_cfg, rec


def age_gap_rule_record(plan, *, switched: bool) -> dict:
    """The age_gap rule of each event's rows: regenerated (prodlib, this run), frozen (the July / fn-fix prodlib
    rows as built: 08-15 rule) and the clone's dept_only rows (08-15 rule)."""
    return {"switch": "REGEN-AGE option A (M)" if switched else "off (October's rendered config)",
            "rules": {"regenerated": AGE_RULE_0815 if switched else AGE_RULE_PIECE_A, "frozen": AGE_RULE_0815,
                      "dept_only": AGE_RULE_0815},
            "by_event": {e: "regenerated" if e in plan.regen else "frozen" for e in plan.m_events}}


def regenerate_m(root: pathlib.Path, v2: pathlib.Path, tables: dict, report: dict, *, stage_cfg: dict,
                 roster: pathlib.Path, base: pathlib.Path | None,
                 first_pub_panel: str | None = None) -> tuple[pathlib.Path, dict]:
    """econ920_lib.regenerate_with_prodlib line for line, with the run's tables, roster pool source and
    stars_excluded base named (October's function reads the October roster and the 08-28 base itself).
    first_pub_panel (M, REGEN-AGE): the U3 panel file; the rendered config then takes the 08-15 first-publication
    rule (m_first_pub). None = October's rendered config."""
    u4_inputs = pa_stage.u4_aug_inputs(stage_cfg)
    stars = pa_stage.event_stars(tables)
    root.mkdir(parents=True, exist_ok=True)
    econ_dir = root / "cal2026-10" / "econ"
    econ_dir.mkdir(parents=True, exist_ok=True)
    rec: dict = {"tables": {f: {"path": str(p), "sha256": sha(p), "n_events": len(stars[f])} for f, p in tables.items()}}
    excl_out = econ_dir / "stars_excluded_cal2026-10.parquet"
    kw = {"person_map": L.person_map_path()}
    if base is not None:
        kw["base"] = base
    rec["stars_excluded"] = pa_stage.build_exclusion(stars, excl_out, **kw)
    rec["stars_excluded"]["rule_version"] = "stage.py: base ∪ event stars ∪ U2 fragments"
    import pyarrow.parquet as pq                                         # noqa: PLC0415
    excluded = set(pq.read_table(excl_out).column("author_id").to_pylist())
    rec["roster_pool"] = pa_stage.build_roster_pool(excluded, econ_dir / "roster_pool_econ_cal2026-10.parquet",
                                                    src=roster)
    inst = pa_stage.school_inst(v2 / fs08.PINNED_LEGACY_CODE_ROSTERLIB)
    rec["u4_aug"] = pa_stage.build_u4_aug(v2, tables["econ"], inst, econ_dir / "u4_aug", **u4_inputs)
    rec["supplement"] = pa_stage.concat_supplements(econ_dir / "edges_supplement_econ_cal2026-10.jsonl")
    rec["person_map"] = pa_stage.assert_stars_in_person_map(stars["econ"])
    mirror = root / "prodlib_econ"
    pcfg = pa_stage.render_config("econ", root, mirror / "runs" / "econ")
    if first_pub_panel is not None:
        rec["first_pub_switch"] = m_first_pub(pcfg, first_pub_panel)
    prun: dict = {}
    out = pa_stage.run_prodlib("econ", mirror, pcfg, prun)
    rec["prodlib"] = prun["prodlib"]["econ"]
    rec["unit_modules"] = prun.get("unit_modules")
    report["regeneration"] = rec
    return out, pcfg


# ================================================================================================ the M phase
#: star_set runs before regenerate (REGEN-AGE): it reads only make_ctx fields, and in M prodlib's restake input takes
#: its ages; the union and freeze steps read ctx.star_set later, as before
ORDER = ("shadow", "ledger", "star_set", "regenerate", "events_filter", "network_freeze", "provenance",
         "predict", "union", "postfilter", "incumbent_stars", "install_union", "rows_proof", "agg_missing",
         "dose_exclusion", "chain", "freeze")


def log_network_freeze(report: dict) -> None:
    """V3-NET's counts to the stage log when the stage stops (a failed stage's work dir is not uploaded):
    relations and rows by class, rows dropped and events left with zero network rows, per row group.
    Counts and event ids only; nothing if V3-NET has not run."""
    if "network_freeze" not in report:
        return
    nfr = report["network_freeze"]
    if nfr is None:
        log("V3-NET was off (switch network_freeze)")
        return
    keep = {k: nfr.get(k) for k in ("parts", "relations_removed", "rows_by_part", "rows_in", "rows_out")}
    log("V3-NET counts at stop " + json.dumps(keep, sort_keys=True, default=str))


def m_phase(ctx, steps) -> None:
    """Run every step in ORDER; a step raises MStop to stop the stage. V3-NET filters the clone's input
    (before predict / union); union_rows_proof sees the unfixed frame; N3 and F13 run after it and before
    the chain. Any stop after V3-NET logs its counts."""
    ctx.report.setdefault("steps", [])
    for name in ORDER:
        t0 = time.time()
        try:
            getattr(steps, name)(ctx)
        except Exception:
            log_network_freeze(ctx.report)
            raise
        ctx.report["steps"].append({"step": name, "secs": round(time.time() - t0, 1)})


class Steps:
    """The real steps. Each reads and writes `ctx` (a SimpleNamespace): v2, cfg, plan, src, stage_cfg,
    work, shadow_root, out, roster, events_dir, calls_dir, patch_extra, patch_r1, report (ctx.report['m'])."""

    def shadow(self, ctx):
        ctx.sh, srec = L.build_econ_shadow(ctx.shadow_root, ctx.v2, removed_new_stars=set(ctx.plan.removed_new_stars),
                                           supplement_extra=L.STAR_ID_SUPPLEMENT, patch_extra=ctx.patch_extra)
        ctx.report["shadow"] = srec

    def ledger(self, ctx):
        plan, gone = ctx.plan, set(ctx.plan.removed_new_events)
        st = L.run_stage("ledger", ctx.work / "ledger_stage", shadow=ctx.shadow_root)
        led0 = st["run_dir"] / "data/event_ledger_fnfix.csv"
        net = st["run_dir"] / "data/network_frame_fnfix.csv"
        walk_l = L.strict_walk(L.FRAMES / "p1_events_ledger_econ.csv", led0, lambda c: c[0] in gone)
        walk_n = L.strict_walk(ctx.v2 / L.ECON / "data/network_frame_fnfix.csv", net, lambda c: c[3] in gone)
        rec = {"secs": st["secs"], "ledger_vs_0828_minus_removed_new": walk_l,
               "network_vs_frozen_minus_removed_new": walk_n}
        if not (walk_l["closed"] and walk_n["closed"]):
            raise MStop("LEDGER_STAGE", sorted(gone), "the ledger stage is not the 08-28 ledger minus the removed new events")
        d1 = L.drop_events_from_csv(led0, set(plan.removed_old), 0, ctx.work / "ledger_minus_removed.csv")
        bad = sorted(e for e, n in d1["removed_lines"].items() if n != 1)
        if bad:
            raise MStop("LEDGER_REMOVED_OLD_HITS", bad)
        blob, d2 = L.correct_id_lines(ctx.work / "ledger_minus_removed.csv", plan.ledger_corrections)
        bad = sorted(e for e in plan.ledger_corrections["events"] if d2["corrected_lines"].get(e) != 1)
        if bad:
            raise MStop("LEDGER_CORRECTION_HITS", bad)
        blob, d3 = finish_ledger(blob, redates=plan.ledger_redates,
                                 appends=[plan.lines[e] for e in plan.ledger_appends], m_events=plan.m_events)
        ctx.ledger = ctx.work / "event_ledger_econ_m.csv"
        ctx.ledger.write_bytes(blob)
        ctx.sh.write(LEDGER_REL, blob, "derived: ledger stage minus removed_old, id-corrected, re-dated in place, "
                                       "new event lines appended (R1 F11)")
        rec.update({"removed_old": d1["removed_lines"], "id_corrected": d2["corrected_lines"], **d3,
                    "sha256": sha(ctx.ledger)})
        ctx.report["ledger"] = rec

    def regenerate(self, ctx):
        tables, _tag = pa_stage.event_tables({f: ctx.events_dir / f"events_{f}_cal2026-10.csv" for f in FIELDS},
                                             root=ctx.events_dir)
        holder: dict = {}
        is_m = ctx.cfg.name == "M"
        stage_cfg, panel, rrec = ctx.stage_cfg, None, None
        if is_m:            # REGEN-AGE: prodlib takes the M star set's ages and the 08-15 first-publication rule
            stage_cfg, rrec = prodlib_restake_m(ctx)
            panel = str(u3_panel_path())
        ctx.prod, ctx.prod_cfg = regenerate_m(ctx.work / "regen", ctx.v2, tables, holder, stage_cfg=stage_cfg,
                                              roster=ctx.roster, base=ctx.exclusion_base, first_pub_panel=panel)
        rec = holder["regeneration"]
        if is_m:
            rec["prodlib_restake"] = rrec
        rec["age_gap_rule"] = age_gap_rule_record(ctx.plan, switched=is_m)
        ctx.blocks, rows = {}, {}
        for e in sorted(ctx.plan.regen):
            block, brec = L.normalise_prodlib_lines(ctx.prod, e)
            ctx.blocks[e] = block
            rows[e] = {"rows": brec["rows"], "persons": brec["persons"]}
        rec["regenerated"] = rows
        rec["events_with_zero_network_rows"] = sorted(e for e, r in rows.items() if r["rows"] == 0)
        ctx.report["regeneration"] = rec
        log(f"prodlib: {len(ctx.plan.regen)} regenerated events in one run, {rec['prodlib']['secs']} s")

    def events_filter(self, ctx):
        net0 = ctx.v2 / L.ECON / "data/network_frame_fnfix.csv"
        regenerate = {v["old"]: e for e, v in ctx.plan.regen.items() if v["old"]}
        fcd = L.filter_events(net0, keep_events=set(ctx.plan.m_events), regenerate=regenerate,
                              spliced=ctx.blocks, out=ctx.work / "net_1_events.csv")
        net1 = pathlib.Path(fcd["output"]["frame"])
        frozen = set(L.read_frame_lines(net0)[1])
        block_set = {ln for b in ctx.blocks.values() for ln in b}
        _h, kept, _t = L.read_frame_lines(net1)
        n_frozen = sum(1 for ln in kept if ln in frozen)
        n_block = sum(1 for ln in kept if ln in block_set and ln not in frozen)
        if n_frozen + n_block != len(kept):
            raise MStop("NETWORK_FILTER_IDENTITY", [], f"{n_frozen} + {n_block} != {len(kept)}")
        ctx.net0, ctx.net1 = net0, net1
        ctx.report["network_filter_c_d"] = {**{k: v for k, v in fcd.items() if k != "input"},
                                            "frozen_frame": fcd["input"],
                                            "kept_rows_byte_identity": {"rows": len(kept), "from_frozen_frame": n_frozen,
                                                                        "from_regenerated_block": n_block}}

    def network_freeze(self, ctx):
        ctx.allowances = None
        if not ctx.cfg.is_on(nf.SWITCH):
            ctx.report["network_freeze"] = None
            return
        d = ctx.work / "network_freeze"
        split = split_net1(ctx.net1, regen=set(ctx.plan.regen), fnfix=fnfix_events(ctx.v2), out_dir=d)
        table = ctx.events_dir / "events_econ_cal2026-10.csv"
        graphs, grec = freeze_graphs(ctx, need_fnfix=split["fnfix"][1] > 0)
        parts, reps, allow = [], {}, {"removed": set(), "to_dept_candidates": set()}
        try:
            for label in FREEZE_PARTS:
                src, n = split[label]
                if n == 0:
                    parts.append(src)
                    reps[label] = None
                    continue
                out, rep = nf.apply(ctx.cfg, src, d / f"{src.stem}_frozen_t1.csv", graph=graphs[label],
                                    event_table=table, report_path=d / f"report_{label}.json")
                parts.append(out)
                reps[label] = {k: rep[k] for k in ("relations_by_class", "rows_by_class", "rows_dropped",
                                                   "events_left_with_zero_rows")}
                a = nf.proof_allowances(rep)
                allow["removed"] |= a["removed"]
                allow["to_dept_candidates"] |= a["to_dept_candidates"]
        except nf.NetworkFreezeStop as e:
            raise MStop(f"NETWORK_FREEZE_{e.code}", _flat_ids(e.ids)) from None
        filtered = d / "net_1_frozen_t1.csv"
        join_frames(parts, filtered)
        ctx.net1 = filtered
        ctx.allowances = allow
        ctx.report["network_freeze"] = {"parts": reps, "graphs": grec, "relations_removed": len(allow["removed"]),
                                        "rows_by_part": {k: n for k, (_p, n) in split.items()},
                                        "rows_in": sum(n for _p, n in split.values()),
                                        "rows_out": len(L.read_frame_lines(filtered)[1]), "sha256": sha(filtered)}

    def star_set(self, ctx):
        rank_age, new = {}, []
        if ctx.src is not None:
            try:
                for e in ctx.plan.m_events:
                    a = e.split(":")[0]
                    if ctx.plan.regen.get(e, {}).get("kind") != "added":
                        rank_age[a] = ctx.src.row("econ", a)["aage"]
            except verdict_source.VerdictMissing as err:
                raise MStop("VERDICT_MISSING", [err.author_id]) from None
            restake = {r["author_id"]: r for r in L.read_rows(ctx.rank_tables / verdict_source.M_ECON)}
            for e in ctx.plan.m_events:
                m = ctx.plan.regen.get(e)
                if not m or m["kind"] != "added":
                    continue
                row = ctx.src.row("econ", m["star"])
                if row["arrival_true"] != int(e.split(":")[1]) or row["school"] != m["school"]:
                    raise MStop("NEW_STAR_RANK_VS_TABLE", [e])
                new.append({"author_id": m["star"], "name": restake.get(m["star"], {}).get("name", ""),
                            "school": m["school"], "arrival": int(e.split(":")[1]), "aage": row["aage"],
                            "rank_pass": row["rank_pass"], "restake": restake.get(m["star"], {})})
        corr = {o.split(":")[0]: n.split(":")[0] for n, v in ctx.plan.regen.items() if v["kind"] == "corrected"
                for o in [v["old"]]}
        signed_pct = None
        if ctx.src is not None:                     # W2-1: M's star set carries the signed admitting-pass value
            signed = ctx.cfg.raw["signed"]
            rows_of = lambda key: _json(ctx.cfg.repo / signed[key][len("repo:"):])["rows"]   # noqa: E731
            signed_pct, prec = signed_percentiles(flips_rows=rows_of("flips"), add_rows=rows_of("add_list"),
                                                  rank_row=lambda a: ctx.src.row("econ", a))
            ctx.report["star_set_percentile"] = prec
        ctx.star_set = ctx.work / "star_set_econ_m.parquet"
        event_stars = {e.split(":")[0] for e in ctx.plan.m_events if ctx.plan.regen.get(e, {}).get("kind") != "added"}
        ctx.report["star_set"] = star_set_m(ctx.v2 / L.ECON / "u4_aug/star_set/star_set.parquet", ctx.star_set,
                                            corr_stars=corr, unstar=set(ctx.plan.unstar),
                                            redates={o: n for o, n in ctx.plan.redates.items()}, new_stars=new,
                                            rank_age=rank_age, event_stars=event_stars, signed_pct=signed_pct)

    def provenance(self, ctx):
        ctx.age_bytes = ctx.sh.path(NEW_EVENTS_REL).read_bytes()
        ctx.prov_bytes = provenance_m(ctx.age_bytes, ctx.plan.regen)
        ctx.prov = ctx.work / "prodlib_events_econ.csv"
        ctx.prov.write_bytes(ctx.prov_bytes)
        ctx.prov_events = {f"{r['author_id']}:{int(r['arrival'])}" for r in L.read_rows(ctx.prov)}
        ctx.report["provenance_table"] = {"sha256": sha(ctx.prov), "rows": len(ctx.prov_events),
                                          "regenerated": sorted(ctx.plan.regen),
                                          "age_table_rows": ctx.age_bytes.count(b"\n") - 1}

    def predict(self, ctx):
        ctx.prediction = R.predict(ctx.net1, ctx.prov_events, f"r1-{ctx.cfg.name}")
        ctx.report["gdose_prediction"] = ctx.prediction

    def union(self, ctx):
        policy = gdose_policy(ctx.cfg)
        ctx.union_cfg = L.union_config(v2=ctx.v2, old_frame=ctx.net1, roster=ctx.roster, ledger=ctx.ledger,
                                       star_set=ctx.star_set, sup_fnfix=ctx.sh.path(SUP_FNFIX_REL),
                                       new_events=ctx.prov, out_dir=ctx.work / "union",
                                       patch_a=ctx.sh.path(L.PATCH_A_REL))
        ctx.report["union_patch_a"] = {"sha256": sha(pathlib.Path(ctx.union_cfg["PATCH_A"])),
                                       "lines": pathlib.Path(ctx.union_cfg["PATCH_A"]).read_bytes().count(b"\n")}
        override = policy == GDOSE_RULING_VALUE and ctx.prediction.get("predicted_gate") == "FAIL"
        # M reads the clone's full G_ROW list for its own G_ROW condition; B0 runs as October did
        capture = clone_g_row_capture() if ctx.cfg.name == "M" else contextlib.nullcontext(None)
        with capture as clone:
            res = L.run_union(ctx.union_cfg, ctx.work / "union_run", ctx.work / "union_run" / "union.log",
                              override_gdose_gate=override)
        ctx.clone_capture = clone
        ctx.report["union"] = {k: v for k, v in res.items() if k != "drawn_relations"}
        try:
            ctx.report["gdose"] = gdose_step(ctx.out, ctx.cfg.name, ctx.prediction, res, override=override,
                                             clone=clone)
        except MStop:
            log_union_checks(pathlib.Path(ctx.union_cfg["OUT_REPORT"]))
            raise
        if "error" in res:
            raise MStop("UNION_GATE_FAILED", [], res["error"].split(" — ")[0])
        ctx.union_res = res

    def postfilter(self, ctx):
        res = ctx.union_res
        pf = L.postfilter_union(pathlib.Path(res["OUT_FRAME"]["path"]), pathlib.Path(res["OUT_REL"]["path"]),
                                ctx.roster, L.person_map_path(), ctx.work / "postfilter", in_post=True)
        ctx.report["postfilter_a_b"] = pf
        ctx.pre_y = pathlib.Path(pf["output"]["pre_y"])
        ctx.rel = pathlib.Path(pf["output"]["relationships"])
        ctx.union_report = pathlib.Path(res["OUT_REPORT"]["path"])
        ctx.inpost_report = ctx.work / "postfilter" / "inpost_report.json"

    def incumbent_stars(self, ctx):
        forms: set[str] = set()
        if ctx.plan.new_stars:
            aliases: dict[str, list[str]] = collections.defaultdict(list)
            for r in L.read_rows(ctx.events_dir / ALIASES):
                aliases[r["person_id"]].append(r["alias_id"])
            forms = star_person_forms(ctx.plan.new_stars, aliases, L.person_map_path())
        rec = drop_incumbent_stars(ctx.pre_y, ctx.rel, forms, ctx.work / "incumbent_stars")
        ctx.pre_y = pathlib.Path(rec["output"]["pre_y"])
        ctx.rel = pathlib.Path(rec["output"]["relationships"])
        ctx.report["incumbent_stars"] = rec

    def install_union(self, ctx):
        for rel, src in ((PRE_Y_REL, ctx.pre_y), (REL_REL, ctx.rel), (UNION_REPORT_REL, ctx.union_report)):
            ctx.sh.install(rel, pathlib.Path(src), "cal-stage:union clone (R1 inputs) post-filtered by (a)+(b) "
                                                   "and the incumbent-star rule")

    def rows_proof(self, ctx):
        m = getattr(getattr(ctx, "cfg", None), "name", None) == "M"
        proof = rows_proof_m(ctx.frozen_pre_y, ctx.pre_y, set(ctx.regen), ctx.allowances, ctx.work,
                             r1_persons=r1_patch_persons(getattr(ctx, "patch_r1", None)),
                             need_outcomes=(getattr(ctx, "clone_capture", None) or {}).get("need_outcomes"),
                             m_rules=m)
        ctx.report["g_row_proof"] = proof
        if not proof["closed"]:
            m = proof.get("m_explained") or {}
            log("rows proof " + json.dumps({**{k: proof.get(k) for k in ("counts", "channel_moves", "allowances")},
                                            "m_explained": {k: m.get(k) for k in m if k != "unexplained_rows"}},
                                           sort_keys=True, default=str))
            for row in (proof.get("samples") or [])[:12] + (m.get("unexplained_rows") or [])[:12]:
                log("rows proof row " + json.dumps(row, sort_keys=True, default=str))
            raise MStop("G_ROW_PROOF", [], "a kept network row is not byte-identical to the frozen pre-y row")

    def agg_missing(self, ctx):
        mode = ctx.cfg.switch("agg_missing")
        rnd = fetch_round(ctx.cfg, ctx.patch_r1)
        code, res = missing_persons.econ_gate(
            ctx.out, ctx.pre_y, ctx.v2 / "fwci_fullsnapshot_rebuild_2026-08-09/data/econ_units_2026-08-09.parquet",
            [ctx.sh.path(L.PATCH_A_REL)], set(ctx.prov_events), mode=mode, round=rnd)
        name = "agg_missing"
        target = ctx.out / (f"stop_report_{name}.json" if code else f"report_{name}.json")
        body = json.loads(target.read_text(encoding="utf-8"))
        body["ids"] = list(body.get("persons", []))          # run_stages.name_free keeps 'ids' (wave-1 issue 9)
        target.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        ctx.report["agg_missing"] = {"code": body["code"], "mode": mode, "round": rnd, "n_persons": body["n_persons"],
                                     "rows": {k: v["rows"] for k, v in res.items()
                                              if isinstance(v, dict) and "rows" in v}}
        ctx.after_fetch = None                   # these old-event rows stay NA in the chain (M review #5)
        if body["code"] == "AGG_MISSING_AFTER_FETCH":
            blk = res[missing_persons.ECON_CLASSES[0]]
            ctx.after_fetch = {"persons": sorted(blk["persons"]), "rows": int(blk["rows"])}
        if code:
            raise MStop(body["code"], body["ids"], name=name, written=True)

    def dose_exclusion(self, ctx):
        mode = "delta" if ctx.cfg.switch("dose_mode") == "delta" else "off"
        if mode == "off":
            ctx.report["dose_exclusion"] = {"mode": "off", "called": False}
            return
        excludes = read_pairs(ctx.calls_dir / "dose_excludes.csv") if ctx.cfg.is_on("dose_excludes") else frozenset()
        addbacks = read_pairs(ctx.calls_dir / "adds.csv") if ctx.cfg.is_on("add_backs") else frozenset()
        before = pathlib.Path(ctx.pre_y)
        try:
            rep = r1_dose_excl.apply_dose_exclusions(before, ctx.work / "dose_excl" / "pre_y_dose_fixed.csv",
                                                     union_cfg=ctx.union_cfg, excludes=excludes,
                                                     addbacks=addbacks, mode=mode)
        except r1_dose_excl.DoseRuleMismatch as e:
            raise MStop("DOSE_RULE_MISMATCH", _flat_ids([[m.get("incumbent_person_id"), m.get("event_id")]
                                                         for m in getattr(e, "mismatches", [])])) from None
        if rep.get("written"):
            fixed = pathlib.Path(rep["path"])
            ctx.sh.install(PRE_Y_REL, fixed, "r1:S6 dose_exclusion (delta)")
            proof = r1_dose_excl.dose_rows_proof(before, fixed, {tuple(x) for x in rep.get("affected", [])})
            rep["dose_rows_proof"] = proof
            if not proof["closed"]:
                raise MStop("DOSE_ROWS_PROOF", [], "the fixed pre-y differs outside the affected dose cells")
            ctx.pre_y = fixed
        rep["called"] = True
        ctx.report["dose_exclusion"] = rep

    def chain(self, ctx):
        ctx.sh.write(NEW_EVENTS_REL, ctx.prov_bytes, "provenance table (age table + every regenerated event) — "
                                                     "for the p1-econ / p2-econ stages (October's arrangement)")
        ch = R.chain_from_union(ctx.work, "m", ctx.shadow_root, ctx.sh, with_split=False)
        ctx.sh.write(NEW_EVENTS_REL, ctx.age_bytes, "restored: the event-age table (no split stage in M, C10)")
        ctx.chain = ch
        ctx.report["chain"] = {k: (str(v) if isinstance(v, pathlib.Path) else v) for k, v in ch.items() if k != "slim"}
        ctx.report["chain"]["slim"] = {k: (str(v) if isinstance(v, pathlib.Path) else v) for k, v in ch["slim"].items()}
        if ch["p1_frame"] is None:
            ok, trec = after_fetch_check(ch, getattr(ctx, "after_fetch", None), ctx.pre_y, set(ctx.prov_events))
            ctx.report["agg_missing_after_fetch_tolerated"] = trec
            if ok:
                written = pathlib.Path(ch["p1_econ"]["unified_frame_written"])
                ctx.sh.install(P1_UNIFIED_REL, written, "cal-stage:p1-econ (m) written frame: 04 exited 2 only on the "
                                                        "AGG_MISSING_AFTER_FETCH old-event rows, kept NA (R1P3-25)")
                ch["p1_frame"] = ctx.sh.path(P1_UNIFIED_REL)
                ctx.report["chain"]["p1_frame"] = str(ch["p1_frame"])
                log(f"p1-econ: {trec['rows']} old-event rows of {len(trec['persons'])} persons stay NA after the fetch")
                return
            res = missing_persons.agg_missing_r1(ctx.pre_y, ctx.v2 / "fwci_fullsnapshot_rebuild_2026-08-09/data/"
                                                 "econ_units_2026-08-09.parquet", [ctx.sh.path(L.PATCH_A_REL)],
                                                 set(ctx.prov_events))
            ids = res["old_event_rows_blocking"]["persons"]
            failed = sorted(k for k, v in trec["checks"].items() if not v)
            raise MStop("P1_ECON_BLOCKED", ids, f"04_rebuild_y.py's own C-PC anchor failed (exit 2); "
                                                f"{trec.get('why') or f'failed checks {failed}'}")

    def freeze(self, ctx):
        ch = ctx.chain
        prods = {"p1_frame": ch["p1_frame"], "p2_frame": ch["p2_frame"], "ledger": ctx.ledger, "rel": ctx.rel,
                 "slim_noev": ch["slim"]["noev"], "slim_ev": ch["slim"]["ev"], "pairs": ch["pairs"],
                 "pre_y": ctx.pre_y, "union_build_report": ctx.sh.path(UNION_REPORT_REL),
                 "panels23_report": ch["panels23_report"], "inpost_report": ctx.inpost_report,
                 "provenance": ctx.prov, "star_set": ctx.star_set,
                 "g_econ_rebuild": (ch["p1_econ"].get("g_econ_rebuild") or {}).get("path")}
        ctx.report["staging_manifest"] = ctx.sh.manifest()
        ctx.report["accounting"] = accounting(ctx)
        freeze_m(ctx.out, prods, ctx.full_report, staging=ctx.sh.manifest())


def _count_lines(p) -> int:
    """Data rows of a CSV with a header line, read in blocks (pairs_unified.csv is ~660 MB)."""
    n = 0
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 24), b""):
            n += block.count(b"\n")
    return n - 1


def october_accounting_keys(*, rel, ub: dict, p2_frame, pairs, slim_stats: dict, relations_dropped: int) -> dict:
    """The keys of October's econ build-report accounting the paper ledgers read (ledger_main: relationships
    after_post_filter_total / _by_channel and rows.pre_y_frame_rows; ledger_carried: p2_rows, slim.rows), in
    October's shape, on this run's products (M review #8; canon M keeps October's schema). The relations
    the incumbent-star rule removed after the in-post report are counted beside them."""
    ch = dict(collections.Counter(r["channel"] for r in L.read_rows(pathlib.Path(rel))))
    return {"relationships": {"union_output_by_channel": ub.get("relationships"),
                              "union_output_persons": (ub.get("frame") or {}).get("persons"),
                              "union_output_events": (ub.get("frame") or {}).get("events"),
                              "after_post_filter_by_channel": ch, "after_post_filter_total": sum(ch.values()),
                              "relations_dropped_incumbent_is_star_r1": relations_dropped},
            "p2_rows": _count_lines(p2_frame), "pairs_rows": _count_lines(pairs), "slim": slim_stats}


def accounting(ctx) -> dict:
    m = ctx.report
    fcd = m["network_filter_c_d"]
    ub = json.loads(pathlib.Path(ctx.union_res["OUT_REPORT"]["path"]).read_text("utf-8"))
    pf = m["postfilter_a_b"]
    oct_keys = october_accounting_keys(rel=ctx.rel, ub=ub, p2_frame=ctx.chain["p2_frame"], pairs=ctx.chain["pairs"],
                                       slim_stats=ctx.chain["slim"].get("stats"),
                                       relations_dropped=m["incumbent_stars"]["relations_dropped"])
    return {**oct_keys, "rows": {
        "frozen_network_frame": fcd["frozen_frame"]["rows"],
        "minus_events_not_in_the_run": -sum(v["rows"] for v in fcd["rows_dropped_event_not_in_set"].values()),
        "minus_regenerated_events_old_rows": -sum(v["rows"] for v in fcd["rows_dropped_regenerated_old_id"].values()),
        "plus_regenerated_rows": sum(fcd["rows_spliced"].values()),
        "minus_network_freeze": -((m["network_freeze"] or {}).get("rows_in", 0) - (m["network_freeze"] or {}).get("rows_out", 0)),
        "union_output_rows": ub["frame"]["rows"],
        "minus_postfilter_a_b": -(pf["input"]["rows"] - pf["output"]["rows"]),
        "minus_incumbent_is_star_r1": -m["incumbent_stars"]["rows_dropped"],
        "pre_y_frame_rows": len(L.read_frame_lines(pathlib.Path(ctx.pre_y))[1]),
        "dose_exclusion_rows_rewritten (row count unchanged)": (m.get("dose_exclusion") or {}).get("rows_changed", 0)},
        "union_relationships_by_channel": ub.get("relationships"),
        "per_event": L.per_event_counts(pathlib.Path(ctx.rel), ctx.chain["p1_frame"], ctx.chain["p2_frame"])}


# ================================================================================================ freeze
FRAMES_ECON = {"p1_frame": "p1_frame_econ.csv", "p2_frame": "p2_becoming_econ.csv",
               "ledger": "p1_events_ledger_econ.csv", "rel": "relationships_econ.csv",
               "slim_noev": "p3_slim_econ.parquet", "slim_ev": "p3_slim_ev_econ.parquet"}
FRAMES_ECON_EXTRA = {"pre_y": "p1_pre_y_frame_econ.csv", "union_build_report": "union_build_report_econ.json",
                     "panels23_report": "panels23_report_econ.json", "inpost_report": "inpost_report_econ.json",
                     "provenance": "prodlib_events_econ.csv", "star_set": "star_set_econ_cal2026-10.parquet",
                     "g_econ_rebuild": "g_econ_rebuild_econ.json"}
#: October's build-report name inside frames_econ/ (the canon readers' file; M review #8)
OCTOBER_BUILD_REPORT = "build_report_econ920_2026-10.json"
AFAR_ECON = {"pairs": "pairs_unified.csv", "p1_frame": "p1_frame_econ.csv", "p2_frame": "p2_becoming_econ.csv",
             "rel": "relationships.csv"}
PAIRS = {"pairs": "pairs_unified.csv", "p2_frame": "becoming_unified.csv"}


def _place(src: pathlib.Path, dest: pathlib.Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        shutil.copyfile(src, dest)
    assert sha(dest) == sha(src), dest


def freeze_m(out, products: dict, report: dict, *, staging: list) -> dict:
    """Write the M econ products ONLY under `out` (= STAGE_OUT): frames_econ/ (+ MANIFEST.sha256, paths
    relative to `out`), afar_econ/, pairs/, build_report_econ_m.json with m.pairs_unified {sha256, bytes}
    (the assemble_frames --pairs-pin key). frames_econ/ carries October's basenames for the canon readers
    (star_set_econ_cal2026-10.parquet, and build_report_econ920_2026-10.json = this run's report['m'] under
    October's key 'october': pairs_unified, regeneration, accounting; M review #8)."""
    out = pathlib.Path(out)
    hit = _inside(out, OCTOBER_ROOTS)
    if hit is not None:
        raise MStop("OUT_IN_OCTOBER_ROOT", [], f"--out lies inside {hit}")
    out.mkdir(parents=True, exist_ok=True)
    root = out.resolve()
    placed: dict[str, str] = {}
    for sub, names in (("frames_econ", {**FRAMES_ECON, **FRAMES_ECON_EXTRA}), ("afar_econ", AFAR_ECON), ("pairs", PAIRS)):
        for key, name in names.items():
            src = products.get(key)
            if src is None:
                continue
            dest = out / sub / name
            assert dest.resolve().parent.parent == root, dest
            _place(pathlib.Path(src), dest)
            placed[f"{sub}/{name}"] = sha(dest)
    (out / "frames_econ" / "staging_manifest_econ_m.json").write_text(
        json.dumps({"entries": staging}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fe = out / "frames_econ"
    pairs = pathlib.Path(products["pairs"])
    report.setdefault("m", {})["pairs_unified"] = {"sha256": sha(pairs), "bytes": pairs.stat().st_size}
    report["m"]["frozen"] = placed
    (fe / OCTOBER_BUILD_REPORT).write_text(json.dumps(
        {"schema": "sar.r1.econ_m_build.october_view.v1", "config": report.get("config"),
         "note": "config M's econ build report under October's key 'october' (canon M keeps October's basenames "
                 "and schema, R1P3-37); the full record is ../build_report_econ_m.json",
         "october": report["m"]}, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    manifest = "".join(f"{sha(p)}  {p.relative_to(out).as_posix()}\n"
                       for p in sorted(fe.rglob("*")) if p.is_file() and p.name != "MANIFEST.sha256")
    (fe / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    (out / BUILD_REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n",
                                    encoding="utf-8")
    return report


# ================================================================================================ the run
#: the 08-28 frames / golds and verified-pool files run_econ920.preconditions checks against their manifests
CONTROL_FROZEN_FRAMES = ("p1_frame_econ.csv", "p1_frame_econ_old79.csv", "p1_frame_econ_new37.csv",
                         "p2_becoming_econ.csv", "p3_slim_econ.parquet", "p3_slim_ev_econ.parquet",
                         "p1_events_ledger_econ.csv")
CONTROL_GOLDS_0828 = ("P1_econ_fnfix", "P1_econ_fnfix_old79", "P1_econ_fnfix_new37", "P2_econ_fnfix")
CONTROL_VERPOOL = ("excluded_persons.csv", "frames/p1_frame_econ_verified.csv", "frames/p2_becoming_econ_verified.csv",
                   "estimates/P1ver_econ.json", "estimates/P2ver_econ.json")


def control_base_files() -> list[pathlib.Path]:
    """The October inputs the controls' precondition step checks in M: base files only (the M sandbox leaves
    them in the clone). October's own step also checks EVENTS_OCT, RESTAKE_OCT and the chemistry / maths
    October event tables - October PRODUCTS, which the sandbox moved to /work/ref/october (M review #2)."""
    return [L.ROSTER_1008, L.STAR_ID_SUPPLEMENT, L.STAR_ID_CORRECTIONS]


def control_preconditions(v2: pathlib.Path) -> dict:
    """run_econ920.preconditions (October, unedited) without its October-build block: the legacy pins, the 920
    roster, the 08-28 frozen frames and golds against data/cal2026-08-28/MANIFEST.sha256, the verified pool, the
    chem/maths A_far inputs, the base files of control_base_files(), the id correction, the person map, Rscript
    and the clone. Dropped: the October event / restake tables and the 113/116/removed_old/A5044432173 event-set
    asserts - they check October's build phase, which M does not run (plan_m checks the M tables), and the
    controls themselves read only the 08-28 canon, the legacy tree and base files. A failed check is a STOP."""
    try:
        rec: dict = {"legacy_pins": L.assert_pins(v2)}
        leg_roster = v2 / "econ_roster_verify_2026-08-09/roster_clean_11school_verified.parquet"
        assert sha(leg_roster) == sha(L.ROSTER_920), "legacy 920 roster != data/raw_verified copy"
        rec["roster_920_sha256"] = sha(L.ROSTER_920)
        man = L.FRAMES_MANIFEST
        for name in CONTROL_FROZEN_FRAMES:
            want = L.manifest_sha(man, f"{L.FRAMES_MANIFEST_PREFIX}/{name}")
            assert sha(L.FRAMES / name) == want, f"{L.FRAMES / name} does not match {man}"
            rec.setdefault("frozen_frames", {})[name] = want
        for label in CONTROL_GOLDS_0828:
            want = L.manifest_sha(man, f"data/cal2026-08-28/estimates/{label}.json")
            assert sha(L.EXPECTED / f"{label}.json") == want, f"08-28 gold {label} does not match {man}"
            rec.setdefault("golds_0828", {})[label] = want
        vman = L.VERPOOL / "MANIFEST.sha256"
        for rel in CONTROL_VERPOOL:
            want = L.manifest_sha(vman, f"data/robustness_2026-09-13_verified_pool/{rel}")
            assert sha(L.VERPOOL / rel) == want, f"verified-pool {rel} does not match its MANIFEST"
            rec.setdefault("verified_pool", {})[rel] = want
        for _rel, src in L.CHEMMATH_AFAR_INPUTS.items():
            assert src.is_file(), src
        for p in control_base_files():
            assert p.is_file(), f"base input missing: {p}"
            rec.setdefault("base_inputs", {})[str(p.relative_to(L.REPO))] = sha(p)
        corr = L.id_correction()
        assert corr["events"] == {R.D5_OLD_EVENT: R.D5_NEW_EVENT}, corr
        rec["id_correction"] = corr
        rec["person_map"] = str(L.person_map_path())
        assert L.person_map_path().is_file(), "U2 person map not on the data disk"
        assert shutil.which("Rscript"), "Rscript not on PATH"
        rec["clone_sha256"] = sha(L.CLONE)
    except AssertionError as e:
        raise MStop("CONTROL_PRECONDITIONS", [], str(e)[:300]) from None
    rec["october_build_checks"] = "not run in M: the October event / restake tables are products (M review #2)"
    return rec


def run_controls(root: pathlib.Path, v2: pathlib.Path, out: pathlib.Path | None, *, preconditions=None) -> dict:
    """October's controls in this root through run_econ920's functions (CLEAR ones of an earlier run in
    the same root are reused). Not CLEAR -> MStop CONTROLS_NOT_CLEAR (the stage exits 1). preconditions:
    control_preconditions (default: M, inside the sandbox) or run_econ920.preconditions (the B0 proof)."""
    R.REPORT.clear()
    R.STOPS.clear()
    prev = root / R.REPORT_NAME
    if prev.is_file():
        R.REPORT.update(json.loads(prev.read_text("utf-8")))
        R.REPORT.pop("stops", None)
    R.REPORT.update({"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                     "authority": "R1 F11 (econ920_m.py): October's controls before the run",
                     "task": "R1 economics through the canonical econ chain", "_t0": time.time()})
    R.REPORT["preconditions"] = (preconditions or control_preconditions)(v2)
    R.save(root)
    fns = {"c1a": R.control_c1a, "gdose": R.measure_gdose, "c1b": R.control_c1b, "c2": R.control_c2, "c3": R.control_c3}
    for phase in CONTROL_PHASES:
        done = (R.verdict_of(phase) == "CLEAR" if phase != "gdose"
                else R.REPORT.get("_gdose_residuals") is not None and
                "gdose_population" in R.REPORT.get("measurements", {}))
        if done:
            log(f"control {phase}: reused from this root")
            continue
        if any(p.name.startswith(phase) for p in root.iterdir()):
            raise MStop("CONTROLS_NOT_CLEAR", [], f"{phase} has scratch in {root} but no CLEAR verdict: use a fresh root")
        t0 = time.time()
        fns[phase](root, v2)
        R.REPORT.setdefault("phase_secs", {})[phase] = round(time.time() - t0, 1)
        R.save(root)
        if R.STOPS:
            raise MStop("CONTROLS_NOT_CLEAR", [], f"{phase}: {R.STOPS[-1][:200]}")
    ctl = {k: R.REPORT[k] for k in ("generated", "authority", "task", "preconditions", "controls", "measurements",
                                    "deviations", "phase_secs") if k in R.REPORT}
    if out is not None:
        (out / CONTROLS_REPORT).write_text(json.dumps(ctl, ensure_ascii=False, indent=1, default=str) + "\n",
                                           encoding="utf-8")
    return {c: R.verdict_of(c) for c in R.CONTROLS}


def patch_extra_file(october: pathlib.Path, r1: pathlib.Path | None, tag: str) -> pathlib.Path:
    """October's supplement ⧺ the R1 supplement, one file inside the repository (build_econ_shadow
    labels it relative to REPO) under output/cal_intermediates/r1/."""
    a = pathlib.Path(october).read_bytes()
    b = pathlib.Path(r1).read_bytes() if r1 else b""
    for name, data in (("--patch-october", a), ("--patch-extra", b)):
        if data and not data.endswith(b"\n"):
            raise MStop("PATCH_SHAPE", [], f"{name} does not end with a newline")
    PATCH_DIR.mkdir(parents=True, exist_ok=True)
    p = PATCH_DIR / f"patch_extra_econ_{tag}.jsonl"
    p.write_bytes(a + b)
    return p


def make_ctx(*, root, v2, cfg, plan, src, stage_cfg, out, roster, events_dir, rank_tables, calls_dir,
             patch_october, patch_r1, exclusion_base_path, report) -> object:
    import types                                                         # noqa: PLC0415
    work = root / "m"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    return types.SimpleNamespace(
        v2=v2, cfg=cfg, plan=plan, src=src, stage_cfg=stage_cfg, out=out, roster=roster, events_dir=events_dir,
        rank_tables=rank_tables, calls_dir=calls_dir, work=work, shadow_root=work / "shadow",
        patch_extra=patch_extra_file(patch_october, patch_r1, plan.name.lower()), patch_r1=patch_r1,
        exclusion_base=exclusion_base_path, regen=plan.regen, after_fetch=None,
        frozen_pre_y=v2 / PRE_Y_REL, full_report=report, report=report["m"])


def run_m(root: pathlib.Path, out: pathlib.Path, cfg, a) -> dict:
    """Controls, then the M phase, for config M and the stage flags."""
    v2 = L.real_v2()
    report: dict = {"schema": "sar.r1.econ_m_build.v1", "config": cfg.name, "config_sha256": cfg.sha256,
                    "generated": datetime.datetime.now().isoformat(timespec="seconds"), "m": {}}
    report["controls"] = run_controls(root, v2, out)
    src = verdict_source.load(a.rank_tables)
    if src.kind != "M":
        raise MStop("RANK_TABLES_KIND", [], f"rank tables kind {src.kind}, want M")
    rank_tables = pathlib.Path(a.rank_tables)
    names = pa_stage._names([rank_tables / verdict_source.M_ECON])
    flips = cfg.repo / cfg.raw["signed"]["flips"][len("repo:"):]
    plan = plan_m(events_dir=a.events, flips=flips, corrections=L.STAR_ID_CORRECTIONS, e0828_table=L.EVENTS_0828,
                  new_events_csv=v2 / L.ECON / "data/new_events_econ.csv", names=names)
    redated = plan.redates
    if redated and not cfg.is_on("redates"):
        raise MStop("REDATES_SWITCH_OFF", sorted(redated))
    report["m"]["redates_map"] = check_redates_map(cfg.raw.get("redates"), redated)
    check_corrections(plan.corr_rows, {e.split(":")[0] for e in redated})
    if plan.new_stars and not cfg.is_on("new_stars"):
        raise MStop("NEW_STARS_SWITCH_OFF", plan.new_stars)
    report["plan"] = plan.summary()
    stage_cfg = {"restake_csv": rank_tables / verdict_source.M_ECON,
                 "restake_label": f"r1 rank tables {verdict_source.M_ECON} (kind M)",
                 "names_csvs": [rank_tables / verdict_source.M_ECON],
                 "events_root": pathlib.Path(a.events), "restake_econ_aug": rank_tables / verdict_source.M_ECON}
    work_tmp = root / "m_inputs"
    work_tmp.mkdir(parents=True, exist_ok=True)
    tables_m = {f: pathlib.Path(a.events) / f"events_{f}_cal2026-10.csv" for f in FIELDS}
    ev_stars = {s for ids in pa_stage.event_stars(tables_m).values() for s in ids}
    aliases = [r["alias_id"] for r in L.read_rows(pathlib.Path(a.events) / ALIASES) if r["person_id"] in ev_stars]
    base = work_tmp / "stars_excluded_base_m.parquet"
    report["m"]["stars_excluded_base"] = exclusion_base(L.CAL08 / "stars_excluded_cal2026-08-28.parquet",
                                                        set(plan.unstar), set(aliases), base)
    ctx = make_ctx(root=root, v2=v2, cfg=cfg, plan=plan, src=src, stage_cfg=stage_cfg, out=out,
                   roster=pathlib.Path(a.roster_econ), events_dir=pathlib.Path(a.events), rank_tables=rank_tables,
                   calls_dir=pathlib.Path(a.calls), patch_october=pathlib.Path(a.patch_october),
                   patch_r1=pathlib.Path(a.patch_extra), exclusion_base_path=base, report=report)
    m_phase(ctx, Steps())
    report["total_secs"] = round(time.time() - R.REPORT["_t0"], 1)
    report["prodlib_secs"] = report["m"]["regeneration"]["prodlib"]["secs"]
    (out / BUILD_REPORT).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n",
                                    encoding="utf-8")
    return report


def run_october_plan(root: pathlib.Path, out: pathlib.Path, *, b0_config="config/r1/B0.json") -> dict:
    """The econ920_null switch-off proof: OCTOBER's plan through this wrapper with every R1 hook off
    (config B0), into `out` (tests/test_r1_econ920_m_real.py)."""
    cfg = r1_config.load(b0_config)
    if cfg.name != "B0":
        raise MStop("CONFIG_NOT_B0", [])
    root, out = pathlib.Path(root), pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    v2 = L.real_v2()
    report: dict = {"schema": "sar.r1.econ_m_build.v1", "config": "B0 (econ920_null)", "m": {}}
    report["controls"] = run_controls(root, v2, out, preconditions=R.preconditions)   # outside the sandbox: October's
    stage_cfg = cfg.resolved("stage")
    names = pa_stage._names(pa_stage.stage_value(stage_cfg, "names_csvs"))
    plan = plan_october(v2, names=names)
    report["plan"] = plan.summary()
    ctx = make_ctx(root=root, v2=v2, cfg=cfg, plan=plan, src=None, stage_cfg=stage_cfg, out=out,
                   roster=L.ROSTER_1008, events_dir=L.CAL10, rank_tables=None, calls_dir=None,
                   patch_october=L.CAL10 / "patch_supplement_2026-10" / "works_by_author_supplement_2026-10.jsonl",
                   patch_r1=None, exclusion_base_path=None, report=report)
    m_phase(ctx, Steps())
    return report


def out_root() -> pathlib.Path:
    v = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not v:
        raise MStop("OUT_ROOT_UNSET", [], f"set ${OUT_ROOT_ENV} to an empty scratch root")
    root = pathlib.Path(v)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()) and not (root / R.REPORT_NAME).is_file():
        raise MStop("OUT_ROOT_NOT_EMPTY", [], f"${OUT_ROOT_ENV} holds files but no {R.REPORT_NAME}")
    if _inside(root, OCTOBER_ROOTS + (REPO / "data",)) is not None:
        raise MStop("OUT_ROOT_IN_REPO_DATA", [])
    return root


def write_stop(out: pathlib.Path, e: MStop) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ids = _flat_ids(e.ids)
    if not e.written:
        body = {"result": "STOP", "code": e.code, "ids": ids, "n_ids": len(ids), "stage": "frames_econ920"}
        (out / f"stop_report_{e.name}.json").write_text(json.dumps(body, indent=1, sort_keys=True) + "\n",
                                                        encoding="utf-8")
    (out / "RESULT.txt").write_text(f"STOP {e.code}\n", encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true", help="required: controls + the M run on the data disk")
    for flag, what in (("--config", "the run config (config/r1/M.json)"),
                       ("--events", "the events stage dir (events_r1.py --mode m)"),
                       ("--rank-tables", "the rank_tables stage dir (restake_r1.py m, kind M)"),
                       ("--calls", "the calls stage dir (dose_excludes.csv, adds.csv)"),
                       ("--roster-econ", "the merged R1 economics roster parquet"),
                       ("--patch-extra", "the assembled R1 works-by-author supplement (patch_assemble.py; may be empty)"),
                       ("--patch-october", "October's works-by-author supplement (data/cal2026-10/patch_supplement_2026-10/...)"),
                       ("--out", "STAGE_OUT")):
        ap.add_argument(flag, required=True, help=what)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule (design v3 §4): econ920_m.py runs only on an R1 AWS instance ($SAR_HOST)")
    if not a.execute:
        print("This runs October's controls and the M economics build on the data disk. Re-run with --execute.",
              file=sys.stderr)
        return 2
    out = pathlib.Path(a.out)
    try:
        if _inside(out, OCTOBER_ROOTS) is not None:
            raise MStop("OUT_IN_OCTOBER_ROOT", [])
        out.mkdir(parents=True, exist_ok=True)
        for stale in (BUILD_REPORT, GDOSE_REPORT, CONTROLS_REPORT, "RESULT.txt"):
            (out / stale).unlink(missing_ok=True)
        for stale in out.glob("stop_report_*.json"):
            stale.unlink()
        try:
            cfg = r1_config.load(a.config)
        except r1_config.ConfigStop as e:
            raise MStop(f"CONFIG_{e.code}", []) from None
        if cfg.name != "M":
            raise MStop("CONFIG_NOT_M", [], "B0 runs the unchanged run_econ920.py (J0)")
        gdose_policy(cfg)
        root = out_root()
        rep = run_m(root, out, cfg, a)
    except MStop as e:
        write_stop(out, e)
        log(f"STOP {e}")
        return 1 if e.code == "CONTROLS_NOT_CLEAR" else 3
    (out / "RESULT.txt").write_text("OK\n", encoding="utf-8")
    log(f"DONE: {len(rep['plan']['regen'])} regenerated events, frames in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
