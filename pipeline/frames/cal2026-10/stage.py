#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/stage.py — the October caliber's STAGING layer for the prodlib network-frame rung
(Piece A of the 2026-09-22 rebuild plan; mirrors pipeline/stars/caliber_2026-08-28/frames_stage.py
and reuses its Shadow / pins / prodlib staging verbatim by import — nothing there is edited).

What it gives a driver
  build_shadow(root, events, *, stage_cfg[, stars_excluded, rosters])
                               the shadow legacy tree the verbatim prodlib resolves its inputs
                               through: hard links for every frozen input the caliber does not
                               change (frames_stage.FROZEN_LINKS), the October event tables and
                               their DERIVED companions at the exact fnfix names for chemistry /
                               math_stats, and a new `cal2026-10/econ/` subtree holding the four
                               derived economics inputs. Every entry is recorded (rel, origin,
                               sha256) in the staging manifest.
  render_config(field, ...)    configs/<field>.json (prodlib schema, placeholders) -> a concrete
                               config dict: ${DERIVED} = <ssd_root>/derived (the data mirror,
                               config/paths.yaml), ${LEGACY_V2} = legacy_v2_output, ${SHADOW} =
                               the shadow root, ${RUN_DIR} = the run directory.
  run_prodlib(field, ...)      stage the pinned prodlib trio (frames_stage.stage_prodlib, sha
                               asserted) and run build_frame.py IN PROCESS with this repo's
                               ported units pre-imported and origin-asserted (the run_cal_frames
                               arrangement), inside a staged_run mark.

The event tables (`events` argument): "cal2026-10" = <events_root>/events_<field>_cal2026-10.csv,
events_root named by the run config's stage section (B0 = data/cal2026-10, the tables written by
pipeline/stars/caliber_2026-10/run_caliber.py; D5), "cal2026-08-28" = the frozen
data/cal2026-08-28/events_<field>_cal.csv (== data/raw_verified/events_<field>_cal2026-08-28.csv,
byte-identical, measured), or a mapping {field: path} naming all three tables ("explicit"). The
tag is written into the staging manifest. There is no "auto" mode any more (R1 F3, 2026-10-15): a
table is named, never chosen by which files happen to exist.

Derived inputs and the rule that makes each (all from tables; nothing hand-typed)
  chemistry / math_stats (the 70_prep companions the signed_csv mode needs)
    events_<field>_fnfix_2026-08-10.csv  = the cal event table's bytes
    shortlist_fnfix.csv                  = frozen shortlist_fnfix rows + one row per cal event whose
                                           (author_id, field, school) is not in it (arrival_year =
                                           arrival_corrected), cal-table order — prodlib inner-joins
                                           the signed table to it, so a superset is exact
    events_<field>_fnfixbase_2026-08-10.csv = frozen fnfixbase rows whose event is still in the cal
                                           table (bytes preserved) + (author:school, arrival) rows
                                           for cal events not in it (the 70_prep_fnfix_inputs.py
                                           42-45 rule; for the 08-28 tables this reproduces
                                           frames_stage.cal_fnfixbase byte for byte — asserted by
                                           run_controls.py)
    stars_excluded_fnfix.parquet         = data/cal2026-08-28/stars_excluded_cal2026-08-28.parquet
                                           UNCHANGED (every chemistry / mathematics event star is
                                           asserted to be in it; a star outside it is a STOP, not
                                           a silent widening)
    edges_supplement_fnfix.jsonl         = data/cal2026-08-28/edges_supplement_cal2026-08-28.jsonl
                                           UNCHANGED
    fnfix/roster_gold_<field>.parquet    = the frozen legacy parquet (hard link; sha asserted equal
                                           to data/raw_verified/roster_gold_<field>.parquet)
  econ (`cal2026-10/econ/`)
    stars_excluded_cal2026-10.parquet    = the 08-28 list (1,837) ∪ every event star of the three cal
                                           tables ∪ (review fix 2026-09-22) EVERY U2 author fragment
                                           of each economics event star's person, ORDER BY author_id.
                                           The fragment expansion is the 08-15 econ machine's own
                                           outcome-exclusion rule (prodlib ship_plevel_poach,
                                           prodlib.py:518-523: frags = every author id folding to a
                                           star person; 116 star persons -> 16,300 excluded works);
                                           a bare-author-id list had silently left 92 fragments /
                                           2,682 snapshot works of 21 multi-fragment stars OUT of the
                                           *_ex_star outcomes. The same list feeds the roster pool,
                                           where the July _roster_pool dropped stars by their own id
                                           (_reports/pool_star_exclusion.json); the fragment rule
                                           additionally drops ONE October roster row (A5038387911,
                                           a fragment of star A5001177483) — recorded in the
                                           derivation as dropped_star_rows. D5: the corrected id A5091326353
                                           enters as an event star; the old id A5090515599 enters as
                                           a fragment of P_A5090515599, the person prodlib seeds as
                                           the star (see below) — not as a star in its own right.
    u4_aug/events/data.parquet           = one row per econ cal event in the legacy u4_aug events
                                           schema (read from the frozen 08-15 parquet): event_id,
                                           star_person_id = star_id, arrival_year, t_minus_1 =
                                           arrival - 1, dept_id = roster_lib.SCHOOL_INST[school]
                                           (the sha-pinned legacy module), arrival_source /
                                           evidence from the table, the four U4 gate columns NULL
    u4_aug/star_set/star_set.parquet     = one row per econ event star in the legacy star_set
                                           schema: is_star_1pct = is_star_5pct = is_foreign_poach =
                                           age_eligible = True for EVERY event star (prodlib seeds a
                                           star's works only when is_star_5pct ∧ is_foreign_poach —
                                           prodlib.py:908-912 — so a False here would silently
                                           truncate that star's two-hop network; the ranking
                                           machine's own p05 flag is a different object and lives
                                           in data/cal2026-10/verdicts_2026-10.csv); the numeric
                                           descriptives come from the run config's stage.restake_csv
                                           where the star has a row, else NULL, and the build report
                                           records stage.restake_label (B0: restake_2026-08-28.csv,
                                           08-28 candidates only — what October used, because
                                           data/cal2026-10/restake_2026-10.csv never existed in
                                           place); name from stage.names_csvs (B0: the 08-28
                                           verdicts table); dept = <school>_econ; subfield the
                                           econ field code the 08-15 builder used for synthesized
                                           rows (read from that frozen parquet, not typed)
    roster_pool_econ_cal2026-10.parquet  = data/cal2026-10/roster_econ_verified_2026-10.parquet in
                                           the DEPT_ROSTER_PANEL 8-column shape (dept_key, author_id,
                                           display_name=NULL, year_start, year_end, evidence,
                                           confidence, human_verified) minus rows whose author_id is
                                           in stars_excluded_cal2026-10 (the 08-15 _roster_pool baked
                                           its star exclusion in the same place); D2/D4: the network
                                           pool IS the verified roster, so the 162 never-verified
                                           people vanish by construction
    edges_supplement_econ_cal2026-10.jsonl = data/raw_verified/edges_supplement_econ_fnfix.jsonl ⧺
                                           data/cal2026-08-28/edges_supplement_cal2026-08-28.jsonl ⧺
                                           data/cal2026-10/edges_supplement_star_id_corrections_2026-10.jsonl
                                           (prodlib's sup_pairs GROUP BY (work, author) de-duplicates;
                                           snapshot rows win in works_domain)
    person map                           = the mirror's U2 parquet, UNCHANGED, referenced directly
                                           (every event star's author_id asserted present — prodlib
                                           fails loud on a missing one, this fails earlier and lists)

Written-down facts about A5091326353 (D5), measured 2026-09-22 on the mirror
  * U2 maps BOTH A5090515599 and A5091326353 to person P_A5090515599 (merge_reason raw_affil_text),
    so at prodlib's person level the star of event A5091326353:2009 is the same person the frozen
    frames had; the correction changes the star's AUTHOR id (ranking layer, supplement seed) not the
    person id. The June snapshot already holds 132 works of A5091326353 (2004-2025) and 8 of
    A5090515599 (2021-2026, the Wenzhou researcher). All 8 foreign works are after the event window
    (arrival 2009, window 2004-2014, dose frozen at 2008), so they touch no dose vector and no
    window outcome. They CAN in principle reach pairs: prodlib's hop1/hop2 closure carries no year
    restriction (the deg-2 "unfrozen" arm, prodlib.py:431-437, produces rows for any bridge year),
    so a post-window coauthor of the Wenzhou fragment could bridge to a roster person. MEASURED on
    the mirror (review, 2026-09-22): the 8 works have 1 coauthor person in the 11-school map and
    that person's coauthors include 0 October-roster persons — no pair. Splitting the person
    cluster would need an override consumed by EVERY econ stage (union clone, panels) and is left
    to the author — recorded as an OPEN item here, not done.
  * The three contaminant works excluded by the calls table (W2013334278, W2066867974, W2356391881;
    2005-2007) are dropped from the SUPPLEMENT but still sit in the snapshot edge table under
    A5091326353 (the snapshot is not re-pulled, by design); MEASURED: they have 0 coauthor persons in
    the 11-school map (no bridge, no pair); their subfields enter the star's 2008 topic vector (a
    small dose_topic effect on his 2009 pairs) — a known, measured limitation, the same class as
    A5091826237's 4 contaminants in the 08-28 layer.
  * The 126-row supplement adds 4 (work, author) edges the snapshot lacks (W2344156049 x3,
    W3121726857 x1, all 2015; none of the four authors is on the October roster, one is in U2) —
    the "adds no new edges" wording of the 09-22 build report was measured on work ids only.

Written-down facts the review added (2026-09-22), measured on the frozen frames and the mirror
  * Where the D2 filter sits. inpost_filter runs on the prodlib OUTPUT frame, not inside the pool.
    That is equivalent to restricting the pool per event to persons in post at arrival because
    prodlib's closure restricts ONLY the incumbent end to the pool: hop1 = any coauthor of the star
    (prodlib.py:392-398, no pool join), hop2 joins pool_tbl on the incumbent i only (:400-406), and
    the deg-1 dedup set is the pre-pool full set (:416-424). No other pool member's presence changes
    a pair, a dose vector or an outcome, so dropping rows afterwards = building with the smaller
    pool. (The union clone's roster channel is a separate join and is not touched here.)
  * Stars as incumbents. The frozen data/frames/p1_frame_econ.csv carries 575 (person, event)
    relations / 6,325 rows whose incumbent is an event-star PERSON of another event (both 26 / 286,
    dept_only 359 / 3,949, network 190 / 2,090; 56 distinct persons) because the July pool excluded
    only the July shipped stars and the fnfix-new stars were never removed from the byte-preserved
    July rows. This build excludes every event star of the three tables (and their fragments) from
    the pool, so the network channel has 0 such relations — the chemistry / mathematics rule
    (silver_parquet minus stars_excluded) applied uniformly. Not a D1-D7 item; written down for the
    author because it changes the population beyond D2/D4.
  * Econ first-pub modes. This config uses works_robust for both star and ego first publication.
    The 08-15 econ machine used star_set_academic_age (from the U4 star_set) and panel_then_wfp
    (U3 panel first_pub_year, then work_first_pub). The earlier note claimed the panel route is
    unavailable — WRONG: u3_panel_11school_2026-07-16 is on the mirror, and panel_then_wfp needs
    only cfg.indept.panel_glob + the snapshot work_first_pub glob (prodlib.py:636-661), not the
    registry_panel indept mode. star_set_academic_age needs academic_age per event star, which
    build_u4_aug fills from the restake table (37/116 today, all stars once restake_2026-10.csv
    exists). Which rule economics should follow is an author decision (age_gap enters every econ
    pair; run_p1.R filters |age_gap| <= 60); run_controls.py E2 measures the difference on the
    frozen 38-event inputs. Nothing here decides it.
  * The frozen 08-15 econ_fnfix config resolves completely on this machine (snapshot copy under
    legacy v2_output/frame_rebuild_2026-07-24/derived_aug, July _roster_pool / registry_v3 / U3
    panel on the mirror), so the economics prodlib rung HAS a byte-level control: run_controls.py
    C1e (frozen frame 08e5756e…, 26,114 rows). The 09-22 build ran only a smoke for econ.

R1 (2026-10-15; F3 + F14 of the R1 plan): every input of this module is named, nothing is chosen
by file existence. The run config's `stage` section (pipeline.lib.r1_config, $SAR_R1_CONFIG; unset
is a STOP) names events_root, restake_csv, restake_label, names_csvs (and, for econ920_lib,
restake_econ_aug and roster_added); October callers read it through stage_config(). Its B0 values
(config/r1/B0.json) are the October constants or the fallback October actually took, so with B0
every product is October's (J0 gate 1). build_shadow also takes two keyword-only switches for the
M chemistry / mathematics driver: stars_excluded (a list replacing the 08-28 list in the membership
STOP and in the fnfix shadow write) and rosters ({field: parquet}, linked over the frozen
roster_gold link exactly as the --roster-variant incfel substitution does, origin recorded). Their
None defaults keep October's behaviour, including the raw_verified roster assert.

Controls (run_controls.py) prove, before any October run: (a) the frozen fnfix inputs through this
module's prodlib runner reproduce the legacy runs/fnfix frames byte for byte; (b) the 08-28 tables
through THESE templates + THIS shadow reproduce the cal2026-08-28 prodlib frames byte for byte (sha
from the 08-28 staging manifest) and the rendered configs equal frames_stage.prodlib_config(cal=True)
key for key; the econ config is smoke-run (no frozen counterpart exists for an all-events run).
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import runpy
import string
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
OLD_LAYER = REPO / "pipeline" / "stars" / "caliber_2026-08-28"
if str(OLD_LAYER) not in sys.path:
    sys.path.insert(0, str(OLD_LAYER))

import frames_stage as fs08                                              # noqa: E402
from analysis.lib.paths import load_paths                                # noqa: E402
from pipeline.lib.paths import staged_run                                # noqa: E402

CAL10 = REPO / "data" / "cal2026-10"
CAL08 = REPO / "data" / "cal2026-08-28"
RAW = REPO / "data" / "raw_verified"
CONFIGS = HERE / "configs"
GOLD = "multidisc_gold_2026-08-10"
ECON_FNFIX = "econ_fnfix_2026-08-15"
FIELDS = ("econ", "chemistry", "math_stats")
FIELDS_GOLD = ("chemistry", "math_stats")
STAR_ID_SUPPLEMENT = CAL10 / "edges_supplement_star_id_corrections_2026-10.jsonl"

sha = fs08.sha


def derived_root() -> pathlib.Path:
    """<ssd_root>/derived — today the local mirror of the S3 copies, mounted at the same path."""
    return pathlib.Path(load_paths()["ssd_root"]) / "derived"


def legacy_v2() -> pathlib.Path:
    return fs08.real_v2()


# ---------------------------------------------------------------------------------------------
# event tables
# ---------------------------------------------------------------------------------------------

def event_tables(events, *, root: pathlib.Path) -> tuple[dict[str, pathlib.Path], str]:
    """field -> event table path, plus the caliber tag. `events` names the tables: "cal2026-10"
    (root/events_<field>_cal2026-10.csv; root = the run config's stage.events_root),
    "cal2026-08-28" (the frozen 08-28 tables; root unused) or {field: path} for all three fields
    ("explicit"). A missing table is a STOP; nothing falls back to another caliber."""
    if isinstance(events, dict):
        if set(events) != set(FIELDS):
            raise ValueError(f"explicit event tables must name exactly {FIELDS}, got {sorted(events)}")
        tables = {f: pathlib.Path(events[f]) for f in FIELDS}
        missing = [str(p) for p in tables.values() if not p.is_file()]
        if missing:
            raise FileNotFoundError(f"explicit event tables not all present: {missing}")
        return tables, "explicit"
    if events == "cal2026-10":
        oct_ = {f: pathlib.Path(root) / f"events_{f}_cal2026-10.csv" for f in FIELDS}
        missing = [str(p) for p in oct_.values() if not p.is_file()]
        if missing:
            raise FileNotFoundError(f"October event tables not all present: {missing}")
        return oct_, events
    if events == "cal2026-08-28":
        aug = {f: CAL08 / f"events_{f}_cal.csv" for f in FIELDS}
        for f in FIELDS:
            assert sha(aug[f]) == sha(RAW / f"events_{f}_cal2026-08-28.csv"), (
                f"data/cal2026-08-28/events_{f}_cal.csv is not the raw_verified copy any more")
        return aug, events
    raise ValueError(f"events must be cal2026-10 | cal2026-08-28 | {{field: path}}, got {events!r} "
                     f"(no 'auto' since R1 F3: a table is named, never chosen by which files exist)")


def read_csv(p: pathlib.Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(p.read_bytes().decode("utf-8"))))


def event_stars(tables: dict[str, pathlib.Path]) -> dict[str, list[str]]:
    """field -> event star author ids, table order (econ column star_id, chem/math author_id)."""
    out = {}
    for f, p in tables.items():
        rows = read_csv(p)
        col = "star_id" if f == "econ" else "author_id"
        out[f] = [r[col] for r in rows]
        assert len(set(out[f])) == len(out[f]), f"duplicate star in {p}"
    return out


# ---------------------------------------------------------------------------------------------
# chemistry / math_stats companions (70_prep shapes)
# ---------------------------------------------------------------------------------------------

def _csv_bytes(fieldnames: list[str], rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


def derived_shortlist(v2: pathlib.Path, tables: dict[str, pathlib.Path]) -> tuple[bytes, dict]:
    src = v2 / GOLD / "data" / "shortlist_fnfix.csv"
    rows = read_csv(src)
    have = {(r["author_id"], r["field"], r["school"]) for r in rows}
    added = []
    for field in FIELDS_GOLD:
        for r in read_csv(tables[field]):
            k = (r["author_id"], r["field"], r["school"])
            if k not in have:
                rows.append({"author_id": r["author_id"], "field": r["field"],
                             "school": r["school"], "arrival_year": r["arrival_corrected"]})
                have.add(k)
                added.append(":".join(k))
    blob = _csv_bytes(["author_id", "field", "school", "arrival_year"], rows)
    assert blob.startswith(src.read_bytes()), "derived shortlist does not byte-preserve the frozen one"
    return blob, {"frozen_rows": len(read_csv(src)), "added": added}


def derived_fnfixbase(v2: pathlib.Path, field: str, table: pathlib.Path) -> tuple[bytes, dict]:
    src = v2 / GOLD / "data" / f"events_{field}_fnfixbase_2026-08-10.csv"
    frozen = read_csv(src)
    cal = read_csv(table)
    cal_ids = {f"{r['author_id']}:{r['school']}": r["arrival_corrected"] for r in cal}
    kept = [r for r in frozen if r["event_id"] in cal_ids]
    dropped = [r["event_id"] for r in frozen if r["event_id"] not in cal_ids]
    have = {r["event_id"] for r in kept}
    added = [{"event_id": e, "arrival_year": a} for e, a in cal_ids.items() if e not in have]
    blob = _csv_bytes(["event_id", "arrival_year"], kept + added)
    return blob, {"frozen_rows": len(frozen), "kept": len(kept), "dropped": dropped,
                  "added": [r["event_id"] for r in added]}


# ---------------------------------------------------------------------------------------------
# econ derived inputs
# ---------------------------------------------------------------------------------------------

def school_inst(shadow_rosterlib: pathlib.Path) -> dict[str, str]:
    """roster_lib.SCHOOL_INST from the sha-pinned legacy module (linked into the shadow)."""
    assert sha(shadow_rosterlib) == fs08.PINNED_LEGACY_CODE[fs08.PINNED_LEGACY_CODE_ROSTERLIB]
    spec = importlib.util.spec_from_file_location("_cal10_roster_lib", shadow_rosterlib)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)                                      # type: ignore[union-attr]
    return dict(mod.SCHOOL_INST)


def _restake_rows(path: pathlib.Path, label: str) -> tuple[dict[str, dict], str]:
    """author_id -> row of `path` (the run config's stage.restake_csv) and the label the build
    report records for it (stage.restake_label). Reads `path` only; an absent file is a STOP."""
    return {r["author_id"]: r for r in read_csv(pathlib.Path(path))}, label


def _names(paths) -> dict[str, str]:
    """author_id -> name over the CSVs given (stage.names_csvs), later files winning; reads no
    other file, and an absent one is a STOP."""
    if isinstance(paths, (str, os.PathLike)):
        raise TypeError(f"_names takes a list of paths, got the single path {paths!r}")
    names = {}
    for p in paths:
        names.update({r["author_id"]: r["name"] for r in read_csv(pathlib.Path(p))})
    return names


# ---------------------------------------------------------------------------------------------
# the run config's `stage` section (R1 F3)
# ---------------------------------------------------------------------------------------------

def stage_config() -> dict:
    """The run config's `stage` section with its repo:/work: tokens resolved
    (pipeline.lib.r1_config; $SAR_R1_CONFIG unset is a STOP, never a default) — the one way an
    October caller obtains the inputs this module and econ920_lib used to choose by existence."""
    from pipeline.lib.r1_config import load_env                         # noqa: PLC0415
    return load_env().resolved("stage")


def stage_value(stage_cfg: dict | None, key: str):
    """stage_cfg[key]; a key the section does not name (or names empty) is a STOP — there is no
    fallback path behind it."""
    if not stage_cfg or stage_cfg.get(key) in (None, "", [], ()):
        raise KeyError(f"the run config's stage section names no {key!r} (every input is named by "
                       f"config; there is no fallback)")
    return stage_cfg[key]


def u4_aug_inputs(stage_cfg: dict | None) -> dict:
    """build_u4_aug's three keyword inputs, from the stage section."""
    return {"restake_csv": pathlib.Path(stage_value(stage_cfg, "restake_csv")),
            "restake_label": stage_value(stage_cfg, "restake_label"),
            "names_csvs": [pathlib.Path(p) for p in stage_value(stage_cfg, "names_csvs")]}


def repo_label(p) -> str:
    """`p` relative to the repo when it lies inside it (October's report strings), else as given."""
    p = pathlib.Path(p)
    for q in (p, p.resolve()):
        if q.is_relative_to(REPO):
            return str(q.relative_to(REPO))
    return str(p)


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def build_u4_aug(v2: pathlib.Path, econ_table: pathlib.Path, inst: dict[str, str],
                 out_dir: pathlib.Path, *, restake_csv: pathlib.Path, restake_label: str,
                 names_csvs) -> dict:
    """The u4_frozen pair prodlib reads, in the frozen 08-15 u4_aug schemas. The restake table, its
    report label and the names tables are the run config's (u4_aug_inputs)."""
    import pyarrow as pa                                               # noqa: PLC0415
    import pyarrow.parquet as pq                                       # noqa: PLC0415
    ev_schema = pq.read_schema(v2 / ECON_FNFIX / "u4_aug" / "events" / "data.parquet")
    ss_frozen = pq.read_table(v2 / ECON_FNFIX / "u4_aug" / "star_set" / "star_set.parquet")
    subfield_codes = {s for s in ss_frozen.column("subfield").to_pylist() if s}
    assert len(subfield_codes) == 1, f"08-15 star_set carries several subfield codes: {subfield_codes}"
    econ_subfield = subfield_codes.pop()
    restake, restake_src = _restake_rows(restake_csv, restake_label)
    names = _names(names_csvs)
    ev_rows, ss_rows = [], []
    for r in read_csv(econ_table):
        a, school, arr = r["star_id"], r["school"], int(r["arrival_year"])
        assert r["event_id"] == f"{a}:{arr}", (r["event_id"], a, arr)
        ev_rows.append({"event_id": r["event_id"], "dept_id": inst[school], "star_person_id": a,
                        "arrival_year": arr, "t_minus_1": arr - 1,
                        "arrival_source": r.get("arrival_source") or None,
                        "arrival_evidence_strength": r.get("arrival_evidence") or None,
                        "modal_inst_year": None, "prior_main_exited": None,
                        "min_tenure_ok": None, "departed_year": None})
        rk = restake.get(a, {})
        cell = rk.get("after_cell") or ""
        ss_rows.append({"author_id": a, "name": names.get(a), "dept": f"{school}_econ",
                        "arrival": arr, "subfield": econ_subfield,
                        "age_bin": cell.split("|")[1] if "|" in cell else None,
                        "academic_age": int(rk["aage"]) if rk.get("aage") not in (None, "") else None,
                        "stock": int(float(rk["after_stock"])) if rk.get("after_stock") else None,
                        "percentile": _f(rk.get("after_pct")),
                        "cell_n": int(float(rk["after_cell_n"])) if rk.get("after_cell_n") else None,
                        "is_star_1pct": True, "is_star_5pct": True, "age_eligible": True,
                        "is_foreign_poach": True})
    (out_dir / "events").mkdir(parents=True, exist_ok=True)
    (out_dir / "star_set").mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(ev_rows, schema=ev_schema), out_dir / "events" / "data.parquet")
    pq.write_table(pa.Table.from_pylist(ss_rows, schema=ss_frozen.schema),
                   out_dir / "star_set" / "star_set.parquet")
    return {"n_events": len(ev_rows), "restake_source": restake_src,
            "n_with_restake_row": sum(1 for r in ss_rows if r["percentile"] is not None),
            "flags_note": "is_star_1pct/5pct/is_foreign_poach/age_eligible True for every event star"
                          " (seeding), econ subfield code read from the 08-15 star_set"}


def build_exclusion(stars: dict[str, list[str]], out: pathlib.Path,
                    person_map: pathlib.Path | None = None,
                    base: pathlib.Path | None = None,
                    fragment_fields: tuple[str, ...] = ("econ",)) -> dict:
    """08-28 list ∪ every event star ∪ (person_map given) every U2 fragment of each star's person
    for the `fragment_fields` — the 08-15 econ outcome-exclusion rule (ship_plevel_poach folds a
    star to its person and excludes every fragment; prodlib.py:518-523). Identity-mapped fields
    (chemistry / math_stats) have no fragments. Returns the row-level accounting."""
    import duckdb                                                      # noqa: PLC0415
    con = duckdb.connect()
    base = base or CAL08 / "stars_excluded_cal2026-08-28.parquet"
    all_stars = sorted({a for ids in stars.values() for a in ids})
    frags: dict[str, list[str]] = {}
    if person_map is not None:
        seeds = sorted({a for f in fragment_fields for a in stars.get(f, [])})
        con.execute("CREATE TABLE seed_t (author_id VARCHAR)")
        if seeds:
            con.executemany("INSERT INTO seed_t VALUES (?)", [(a,) for a in seeds])
        for a, f in con.execute(f"""
            SELECT s.author_id, q.author_id FROM seed_t s
            JOIN read_parquet('{person_map.as_posix()}') p USING (author_id)
            JOIN read_parquet('{person_map.as_posix()}') q ON q.person_id = p.person_id
            WHERE q.author_id <> s.author_id ORDER BY 1, 2""").fetchall():
            frags.setdefault(a, []).append(f)
    frag_ids = sorted({f for v in frags.values() for f in v} - set(all_stars))
    con.execute("CREATE TABLE add_t (author_id VARCHAR)")
    if all_stars + frag_ids:
        con.executemany("INSERT INTO add_t VALUES (?)", [(a,) for a in all_stars + frag_ids])
    con.execute(f"COPY (SELECT author_id FROM read_parquet('{base.as_posix()}') UNION "
                f"SELECT author_id FROM add_t ORDER BY author_id) TO '{out.as_posix()}' "
                f"(FORMAT PARQUET)")
    n_base = con.execute(f"SELECT count(*) FROM read_parquet('{base.as_posix()}')").fetchone()[0]
    n_out = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    in_base = {t[0] for t in con.execute(
        f"SELECT author_id FROM read_parquet('{base.as_posix()}')").fetchall()}
    con.close()
    return {"base_08_28": n_base, "event_stars": len(all_stars),
            "added": sorted(set(all_stars) - in_base), "total": n_out,
            "fragment_rule": "every U2 fragment of each event star's person for "
                             + ",".join(fragment_fields) + " (08-15 ship_plevel_poach semantics)",
            "stars_with_fragments": len(frags), "fragments_added": frag_ids,
            "fragments_by_star": frags}


def build_roster_pool(excluded: set[str], out: pathlib.Path,
                      src: pathlib.Path | None = None) -> dict:
    import duckdb                                                      # noqa: PLC0415
    src = src or CAL10 / "roster_econ_verified_2026-10.parquet"
    con = duckdb.connect()
    con.execute("CREATE TABLE ex_t (author_id VARCHAR)")
    if excluded:                                  # duckdb executemany rejects an empty list
        con.executemany("INSERT INTO ex_t VALUES (?)", [(a,) for a in sorted(excluded)])
    n_src, n_null = con.execute(
        f"SELECT count(*), sum(CASE WHEN year_start IS NULL OR year_end IS NULL THEN 1 ELSE 0 END) "
        f"FROM read_parquet('{src.as_posix()}')").fetchone()
    assert not n_null, f"October roster has {n_null} rows with an open spell end"
    con.execute(f"""COPY (
        SELECT r.dept_key, r.author_id, CAST(NULL AS VARCHAR) AS display_name,
               CAST(r.year_start AS SMALLINT) AS year_start, CAST(r.year_end AS SMALLINT) AS year_end,
               r.evidence, r.confidence, r.human_verified
        FROM read_parquet('{src.as_posix()}') r
        WHERE r.author_id NOT IN (SELECT author_id FROM ex_t)
        ORDER BY r.dept_key, r.author_id, r.year_start) TO '{out.as_posix()}' (FORMAT PARQUET)""")
    n_out = con.execute(f"SELECT count(*) FROM read_parquet('{out.as_posix()}')").fetchone()[0]
    dropped = [t[0] for t in con.execute(
        f"SELECT author_id FROM read_parquet('{src.as_posix()}') WHERE author_id IN "
        f"(SELECT author_id FROM ex_t) ORDER BY 1").fetchall()]
    con.close()
    return {"source": str(src.relative_to(REPO)) if src.is_relative_to(REPO) else str(src),
            "source_sha256": sha(src), "rows_in": n_src,
            "rows_out": n_out, "dropped_star_rows": dropped}


def assert_stars_in_person_map(stars: list[str]) -> dict:
    import duckdb                                                      # noqa: PLC0415
    pm = derived_root() / "u2_person_map_11school_2026-07-16" / "person_map" / "data.parquet"
    con = duckdb.connect()
    con.execute("CREATE TABLE st (author_id VARCHAR)")
    con.executemany("INSERT INTO st VALUES (?)", [(a,) for a in stars])
    rows = con.execute(f"SELECT s.author_id, p.person_id FROM st s LEFT JOIN "
                       f"read_parquet('{pm.as_posix()}') p USING (author_id) ORDER BY 1").fetchall()
    con.close()
    missing = [a for a, p in rows if p is None]
    assert not missing, f"event stars missing from the U2 person map (prodlib would STOP): {missing}"
    persons = {}
    for a, p in rows:
        persons.setdefault(p, []).append(a)
    shared = {p: v for p, v in persons.items() if len(v) > 1}
    return {"person_map": str(pm), "person_map_sha256": sha(pm), "n_stars": len(stars),
            "stars_sharing_a_person": shared}


def concat_supplements(out: pathlib.Path) -> dict:
    parts = [RAW / "edges_supplement_econ_fnfix.jsonl", CAL08 / "edges_supplement_cal2026-08-28.jsonl",
             STAR_ID_SUPPLEMENT]
    rec = []
    with open(out, "wb") as f:
        for p in parts:
            b = p.read_bytes()
            assert b.endswith(b"\n"), f"{p} does not end with a newline"
            f.write(b)
            rec.append({"part": str(p.relative_to(REPO)), "lines": b.count(b"\n"), "sha256": sha(p)})
    return {"parts": rec, "lines": sum(r["lines"] for r in rec)}


# ---------------------------------------------------------------------------------------------
# the shadow
# ---------------------------------------------------------------------------------------------

def build_shadow(root: pathlib.Path, events, *, stage_cfg: dict,
                 stars_excluded: pathlib.Path | None = None,
                 rosters: dict[str, pathlib.Path] | None = None) -> tuple[fs08.Shadow, dict]:
    """The full input shadow for the three prodlib runs. Returns (shadow, derivation record).

    stage_cfg   the run config's `stage` section (stage_config(); event tables root, restake and
                names tables) — required, no default.
    stars_excluded  None = October: the 08-28 list is the chemistry / math_stats membership STOP
                and the fnfix stars_excluded. A path (the M list) replaces it in both places.
    rosters     None = October: the frozen roster_gold links, sha asserted equal to raw_verified.
                {field: parquet} re-points that field's link at the given file (the incfel
                precedent of run_cal_frames_chemmath), origin and sha recorded."""
    v2 = legacy_v2()
    assert v2.is_dir(), f"legacy v2_output not on this machine: {v2}"
    tables, tag = event_tables(events, root=pathlib.Path(stage_value(stage_cfg, "events_root")))
    u4_aug_inputs(stage_cfg)                         # the econ subtree's keys: a gap STOPs before any work
    if rosters is not None and not set(rosters) <= set(FIELDS_GOLD):
        raise ValueError(f"rosters may name only {FIELDS_GOLD}, got {sorted(rosters)}")
    stars = event_stars(tables)
    rec: dict = {"events": tag, "tables": {f: {"path": repo_label(p), "sha256": sha(p),
                                               "n_events": len(stars[f])}
                                           for f, p in tables.items()}}
    sh = fs08.Shadow(root / "v2_output")
    for rel in fs08.FROZEN_LINKS:
        sh.link_frozen(rel, v2 / rel)
    assert sha(sh.path(fs08.PINNED_LEGACY_CODE_ROSTERLIB)) == \
        fs08.PINNED_LEGACY_CODE[fs08.PINNED_LEGACY_CODE_ROSTERLIB], "roster_lib.py pin broken"
    for field in FIELDS_GOLD:
        rel_r = f"{GOLD}/data/fnfix/roster_gold_{field}.parquet"
        if rosters is not None and field in rosters:
            src = pathlib.Path(rosters[field])
            sh.link_frozen(rel_r, src)                     # one re-pointed link (the incfel precedent)
            sh.entries[-1]["origin"] = f"r1:roster_gold_{field} <- {repo_label(src)}"
            rec.setdefault("rosters", {})[field] = {"source": repo_label(src),
                                                    "sha256": sh.entries[-1]["sha256"]}
        else:
            assert sha(sh.path(rel_r)) == sha(RAW / f"roster_gold_{field}.parquet"), \
                f"legacy roster_gold_{field} != raw_verified"

    # --- chemistry / math_stats at the fnfix names ------------------------------------------
    gold = f"{GOLD}/data"
    excl = CAL08 / "stars_excluded_cal2026-08-28.parquet" if stars_excluded is None \
        else pathlib.Path(stars_excluded)
    import duckdb                                                      # noqa: PLC0415
    con = duckdb.connect()
    in_excl = {t[0] for t in con.execute(
        f"SELECT author_id FROM read_parquet('{excl.as_posix()}')").fetchall()}
    con.close()
    for field in FIELDS_GOLD:
        outside = [a for a in stars[field] if a not in in_excl]
        assert not outside, (f"{field} event star(s) not in {excl.stem} — a STOP, "
                             f"not a silent widening: {outside}")
        sh.write(f"{gold}/events_{field}_fnfix_2026-08-10.csv", tables[field].read_bytes(),
                 f"cal:{repo_label(tables[field])} ({tag})")
        blob, d = derived_fnfixbase(v2, field, tables[field])
        sh.write(f"{gold}/events_{field}_fnfixbase_2026-08-10.csv", blob,
                 f"derived:frozen fnfixbase filtered to the cal events + cal admissions (70_prep rule)")
        rec.setdefault("fnfixbase", {})[field] = d
    blob, d = derived_shortlist(v2, tables)
    sh.write(f"{gold}/shortlist_fnfix.csv", blob, "derived:frozen shortlist_fnfix + cal admissions")
    rec["shortlist"] = d
    if stars_excluded is None:
        sh.write(f"{gold}/stars_excluded_fnfix.parquet", excl.read_bytes(),
                 "cal:stars_excluded_cal2026-08-28.parquet (unchanged for chemistry/math_stats)")
    else:
        sh.write(f"{gold}/stars_excluded_fnfix.parquet", excl.read_bytes(),
                 f"r1:{repo_label(excl)} (the run's stars_excluded for chemistry/math_stats)")
        rec["stars_excluded_chemmath"] = {"source": repo_label(excl), "sha256": sha(excl),
                                          "n": len(in_excl)}
    sh.write(f"{gold}/edges_supplement_fnfix.jsonl",
             (CAL08 / "edges_supplement_cal2026-08-28.jsonl").read_bytes(),
             "cal:edges_supplement_cal2026-08-28.jsonl (unchanged for chemistry/math_stats)")

    _econ_subtree(root, sh, v2, tables, stars, rec, stage_cfg=stage_cfg)
    return sh, rec


def _econ_subtree(root: pathlib.Path, sh: fs08.Shadow, v2: pathlib.Path,
                  tables: dict[str, pathlib.Path], stars: dict[str, list[str]], rec: dict, *,
                  stage_cfg: dict) -> None:
    """build_shadow's `cal2026-10/econ/` subtree (the four derived economics inputs), its entries
    appended to `sh` after the chemistry / math_stats ones and its records into `rec`."""
    econ_dir = root / "cal2026-10" / "econ"
    econ_dir.mkdir(parents=True, exist_ok=True)
    sh_econ = fs08.Shadow(root / "cal2026-10")
    excl_out = econ_dir / "stars_excluded_cal2026-10.parquet"
    pm_path = derived_root() / "u2_person_map_11school_2026-07-16" / "person_map" / "data.parquet"
    rec["stars_excluded"] = build_exclusion(stars, excl_out, person_map=pm_path)
    sh_econ.entries.append({"rel": "econ/stars_excluded_cal2026-10.parquet",
                            "origin": "derived:cal2026-08-28 list ∪ every event star of the three tables"
                                      " ∪ every U2 fragment of each econ event star's person",
                            "sha256": sha(excl_out)})
    excluded = set()
    import pyarrow.parquet as pq                                       # noqa: PLC0415
    excluded = set(pq.read_table(excl_out).column("author_id").to_pylist())
    pool_out = econ_dir / "roster_pool_econ_cal2026-10.parquet"
    rec["roster_pool"] = build_roster_pool(excluded, pool_out)
    sh_econ.entries.append({"rel": "econ/roster_pool_econ_cal2026-10.parquet",
                            "origin": "derived:roster_econ_verified_2026-10 in DEPT_ROSTER_PANEL shape minus"
                                      " excluded stars", "sha256": sha(pool_out)})
    inst = school_inst(sh.path(fs08.PINNED_LEGACY_CODE_ROSTERLIB))
    rec["u4_aug"] = build_u4_aug(v2, tables["econ"], inst, econ_dir / "u4_aug", **u4_aug_inputs(stage_cfg))
    for rel in ("econ/u4_aug/events/data.parquet", "econ/u4_aug/star_set/star_set.parquet"):
        sh_econ.entries.append({"rel": rel, "origin": f"derived:from {repo_label(tables['econ'])}",
                                "sha256": sha(root / "cal2026-10" / rel)})
    sup_out = econ_dir / "edges_supplement_econ_cal2026-10.jsonl"
    rec["supplement"] = concat_supplements(sup_out)
    sh_econ.entries.append({"rel": "econ/edges_supplement_econ_cal2026-10.jsonl",
                            "origin": "derived:econ_fnfix ⧺ cal2026-08-28 ⧺ star_id_corrections supplements",
                            "sha256": sha(sup_out)})
    rec["person_map"] = assert_stars_in_person_map(stars["econ"])
    sh.entries.extend({**e, "rel": "cal2026-10/" + e["rel"]} for e in sh_econ.entries)


# ---------------------------------------------------------------------------------------------
# configs + the prodlib runner
# ---------------------------------------------------------------------------------------------

def render_config(field: str, shadow_root: pathlib.Path, run_dir: pathlib.Path) -> dict:
    tpl = (CONFIGS / f"{field}.json").read_text(encoding="utf-8")
    vals = {"DERIVED": str(derived_root()), "LEGACY_V2": str(legacy_v2()),
            "SHADOW": str(shadow_root), "RUN_DIR": str(run_dir)}
    rendered = string.Template(tpl).substitute(vals)
    assert "${" not in rendered, "unrendered placeholder left in the config"
    return json.loads(rendered)


def run_prodlib(field: str, mirror: pathlib.Path, cfg: dict, report: dict) -> pathlib.Path:
    """Stage the pinned prodlib trio and run build_frame.py on `cfg`, in process, with THIS repo's
    ported units pre-imported and origin-asserted (run_cal_frames.run_prodlib, unchanged)."""
    shas = fs08.stage_prodlib(mirror)
    cfg_p = mirror / f"config_{field}.json"
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    report.setdefault("unit_modules", fs08.preimport_prodlib_units())
    target = mirror / "code" / "build_frame.py"
    argv0 = sys.argv
    t0 = time.time()
    try:
        sys.argv = [str(target), str(cfg_p)]
        buf = io.StringIO()
        from contextlib import redirect_stdout                       # noqa: PLC0415
        with staged_run(target), redirect_stdout(buf):
            runpy.run_path(str(target), run_name="__main__")
    finally:
        sys.argv = argv0
    tail = buf.getvalue().strip().splitlines()
    assert tail and tail[-1].startswith("BUILD_DONE"), tail[-3:]
    out = pathlib.Path(cfg["run_dir"]) / "data" / "analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
    assert out.is_file(), out
    rep = json.loads((pathlib.Path(cfg["run_dir"]) / "build_report.json").read_text("utf-8"))
    report.setdefault("prodlib", {})[field] = {
        "code_sha256": shas, "secs": round(time.time() - t0, 1), "config": str(cfg_p),
        "frame": str(out), "frame_sha256": sha(out), "frame_lines": out.read_bytes().count(b"\n"),
        "build_report": {k: rep.get(k) for k in ("pool", "deg2_hops", "export", "roster_diag",
                                                  "events_diag", "topic_dose", "subgraph")}}
    return out


if __name__ == "__main__":
    print(__doc__)
