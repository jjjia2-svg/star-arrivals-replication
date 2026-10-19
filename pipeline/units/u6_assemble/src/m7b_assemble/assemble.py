"""assemble: the sole producer of analysis_frame_p01/p05 (HIGH-1; D1 two files).

Row sources (C3, two roots): treated rows = PAIRWISE_DOSE distinct (i,star,event), nothing added or removed;
year row set = arrival ± RED cohort.event_window_years (=5, including the pre-period for the downstream
anticipation test C1). C rows (never-treated, #6 plan B): the pool is empty for the two universities -> 0 rows (left open).

Outcome fill (R7, plan C; see the fill_outcomes docstring):
  (1) years with output -> take OUTPUT directly; (2) employed (authority = table B) years with zero output -> 0 for sum-type / NA for mean-type;
  (3) non-employed zero-output years (including after complete exit) -> all NA. Never fill 0 and never fabricate control columns.

Frame v1.1 fixes: (a) FWCI cannot be computed (papers exist,
  baseline entirely missing, crushed to 0 by the upstream nansum) -> the frame records NA (fill_outcomes); (b) roster conflict resolution
  prefers human_verified (incumbent_roster.resolve_roster_conflicts, overlap case);
  (c) events that drop out of the frame for zero coupling are counted explicitly (coverage events_nominal/in_frame/dropped).

age_gap (#7 arrival frozen / #9 true career first publication): U4 does not currently write a generation_pair table ->
  star first-publication year = star_set.arrival − 1 − academic_age,
  incumbent first-publication year = panel.first_pub_year (a missing person falls back to U1 work_first_pub; the robust correction
  applies only to star candidates, and the whole incumbent pool is left untouched); direction = identity/cohort.academic_age_gap
  (star − ego). The 3-tuple -> 4-tuple year broadcast is a constant (not expected to fan out).

Guards: dose triple unique (H5) / frozen_at_year == events.t_minus_1 (reconciliation HALT) /
star flag matches the p-level (C2) / exactly 15 columns in the schema / PK unique / NA rate C2 (>20% HUMAN_REVIEW)
/ pop-min violations are counted, not silently dropped (D5 x C3 conflict point, needs manual review) / hand-written six-key tally (op_id arm N/A).

Products: frame x2 + groups x2 in one COMMIT (write_dataset_commit, physically guaranteeing the two tables share one source)
+ one sidecar _manifest.json {row_count, pk_sha256} per frame (B6-MANIFEST-SIDECAR)
+ coverage_groups.json + output_diag.json (diagnostics go to sidecars and are not mixed into the TALLY).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Callable, Iterable

import pyarrow as pa
import pyarrow.parquet as pq

from common._redlines import RED
from common.atomic_io import atomic_write_bytes
from common.manifest import write_dataset_commit
from common.reconcile import assert_invariant_monotone
from common.schema import ANALYSIS_FRAME, TALLY, assert_matches_schema
from identity.cohort import academic_age_gap
from identity.exit_codes import STRUCTURAL_GATE_FAIL

from . import groups_io
from . import incumbent_roster as ir

P_LEVELS: tuple = ("p01", "p05")
FRAME_PK: tuple = ("incumbent_person_id", "year", "star_person_id", "event_id")
STAR_FLAG_BY_LEVEL: dict = {"p01": "is_star_1pct", "p05": "is_star_5pct"}

# R7 fill types (plan C: sum-type with employed zero output = true 0; mean-type with a 0-paper year = NA, never fill 0)
SUM_TYPE_COLS: tuple = ("fwci_frac", "fwci_frac_ex_star", "pub_count",
                        "pub_count_ex_star")
MEAN_TYPE_COLS: tuple = ("fwci_mean", "fwci_mean_ex_star")

# Frame column -> OUTPUT column (after the 15-column final form all names match and are taken directly; the old rename bridge is retired)
_OUTCOME_COLS: tuple = SUM_TYPE_COLS + MEAN_TYPE_COLS

# Deterministic write parameters (same as U1 _writer_util; U6 does not import the U1 writer —
# frame column types must be made explicit arrow int16/float32, see _arrow_type)
_PARQUET_KW: dict = {"compression": "zstd", "use_dictionary": False,
                     "write_statistics": False, "store_schema": False}

_ARROW_TYPES = {"str": pa.string(), "int16": pa.int16(), "bool": pa.bool_(),
                "float32": pa.float32()}


class FrameAssemblyError(Exception):
    """Structural assembly failure (dose degree fan-out / frozen-year reconciliation / star-flag mismatch / missing first-publication year)."""

    exit_code: int = STRUCTURAL_GATE_FAIL


# ---------------------------------------------------------------------------
# Pre-guards
# ---------------------------------------------------------------------------
def dose_unique_triples(dose_rows: Iterable[dict]) -> dict:
    """H5/B6-DEGREE-UNIQ: unique per (i,star,event) (degree was already collapsed to one row by U5); raise if not."""
    out: dict = {}
    for d in dose_rows:
        key = (d["incumbent_person_id"], d["star_person_id"], d["event_id"])
        if key in out:
            raise FrameAssemblyError(
                f"PAIRWISE_DOSE triple not unique (degree fan-out?): {key!r}")
        out[key] = d
    return out


def _check_dose_against_events(triples: dict, events_by_id: dict,
                               star_by_author: dict, p_level: str) -> None:
    flag = STAR_FLAG_BY_LEVEL[p_level]
    for (_i, _s, event_id), d in triples.items():
        ev = events_by_id.get(event_id)
        if ev is None:
            raise FrameAssemblyError(f"dose references a nonexistent event {event_id!r}")
        if d["frozen_at_year"] != ev["t_minus_1"]:
            raise FrameAssemblyError(
                f"dose frozen_at_year={d['frozen_at_year']} != events.t_minus_1="
                f"{ev['t_minus_1']} (event {event_id!r}) — freeze-point reconciliation does not balance, HALT")
        star = star_by_author.get(ev["star_person_id"])
        if star is None:
            raise FrameAssemblyError(
                f"event star {ev['star_person_id']!r} not in star_set")
        if not star.get(flag):
            raise FrameAssemblyError(
                f"the star of event {event_id!r} lacks the {flag} flag — dose does not match the p-level star set")


def star_first_pub_by_event(events_by_id: dict, star_by_author: dict) -> dict:
    """Star first-publication year = arrival − 1 − academic_age (derivable from the current 14 columns of star_set)."""
    out: dict = {}
    for event_id, ev in events_by_id.items():
        star = star_by_author.get(ev["star_person_id"])
        if star is None:
            continue
        if star.get("academic_age") is None or star.get("arrival") is None:
            raise FrameAssemblyError(
                f"star_set row lacks arrival/academic_age; the star's first-publication year cannot be derived: {event_id!r}")
        out[event_id] = int(star["arrival"]) - 1 - int(star["academic_age"])
    return out


def first_pub_of_persons(panel_rows: Iterable[dict], person_map_rows: list,
                         work_first_pub: dict, *, max_leading_gap=None) -> dict:
    """Incumbent first-publication year: panel.first_pub_year first, falling back to U1 work_first_pub for a missing person.

    The fallback uses the shared **robust debut year** (identity.first_pub.robust_first_pub) instead of the bare min(fragment first-publication year):
      a contaminated fragment year that leads alone in the fragment min-year set
      (separated from the other fragments by more than the configured gap=10) is dropped, and the earliest year of the contiguous fragments is kept.
      The panel main path is taken directly (U3 already produced the robust value; no second cleaning).
      max_leading_gap is passed explicitly by the caller (None while reaching the robust fallback ->
      RedlineUnsigned; a default is never assumed).
    """
    from identity.first_pub import robust_first_pub

    fp: dict = {}
    for p in panel_rows:
        v = p.get("first_pub_year")
        if v is None:
            continue
        prev = fp.get(p["person_id"])
        fp[p["person_id"]] = v if prev is None else min(prev, v)
    if work_first_pub:
        frags: dict = {}
        for r in person_map_rows:
            frags.setdefault(r["person_id"], []).append(r["author_id"])
        for pid, authors in frags.items():
            if pid in fp:
                continue
            vals = [work_first_pub[a] for a in authors if a in work_first_pub]
            if vals:
                fp[pid] = robust_first_pub(vals, max_leading_gap=max_leading_gap)
    return fp


# ---------------------------------------------------------------------------
# R7 outcome fill (pure function)
# ---------------------------------------------------------------------------
def fill_outcomes(pk_rows: list, output_rows: list,
                  in_dept_years: Callable[[str], frozenset]) -> tuple[list, dict]:
    """OUTPUT left-join for (incumbent, year) + the R7 three-form fill.

    (1) OUTPUT has a row -> the six outcomes are taken directly (real publications, including years still publishing after leaving the department);
    (2) no row + employed that year (table B authority) -> SUM_TYPE 0.0 / MEAN_TYPE None;
    (3) no row + not employed that year (before joining / after leaving / after complete exit) -> all None.

    Fix: in form (1), years with "papers but the FWCI baseline entirely missing" (pub_count>0 AND fwci_mean=NA AND fwci_frac=0, where the
    upstream nansum crushed an uncomputable value to 0) -> fwci_frac is recorded as NA (R7/C=NA semantics); the ex_star triple
    likewise. A true zero citation (fwci_mean=0) has different semantics and stays 0. Counts go into diag for audit.
    """
    out_by_iy = {(o["incumbent_person_id"], o["year"]): o for o in output_rows}
    n_from_output = n_zero_fill = n_na = 0
    n_uncomp = n_uncomp_ex = 0
    rows: list = []
    for r in pk_rows:
        key = (r["incumbent_person_id"], r["year"])
        o = out_by_iy.get(key)
        if o is not None:
            for c in _OUTCOME_COLS:
                v = o[c]
                r[c] = None if v is None else float(v)
            if (r["pub_count"] or 0) > 0 and r["fwci_mean"] is None \
                    and r["fwci_frac"] == 0.0:
                r["fwci_frac"] = None
                n_uncomp += 1
            if (r["pub_count_ex_star"] or 0) > 0 \
                    and r["fwci_mean_ex_star"] is None \
                    and r["fwci_frac_ex_star"] == 0.0:
                r["fwci_frac_ex_star"] = None
                n_uncomp_ex += 1
            n_from_output += 1
        elif r["year"] in in_dept_years(r["incumbent_person_id"]):
            for c in SUM_TYPE_COLS:
                r[c] = 0.0
            for c in MEAN_TYPE_COLS:
                r[c] = None
            n_zero_fill += 1
        else:
            for c in _OUTCOME_COLS:
                r[c] = None
            n_na += 1
        rows.append(r)
    n = len(rows) or 1
    diag = {
        "n_rows": len(rows),
        "n_from_output": n_from_output,
        "n_indept_zero_fill": n_zero_fill,
        "n_not_indept_na": n_na,
        "n_fwci_uncomputable_to_na": n_uncomp,
        "n_fwci_uncomputable_to_na_ex_star": n_uncomp_ex,
        "na_rate_fwci_frac": sum(1 for r in rows if r["fwci_frac"] is None) / n,
    }
    return rows, diag


# ---------------------------------------------------------------------------
# Frame serialization (deterministic + explicit types) and PK sha
# ---------------------------------------------------------------------------
def _frame_table(rows: list) -> pa.Table:
    cols = list(ANALYSIS_FRAME)
    arrays = {}
    for c in cols:
        arrays[c] = pa.array([r[c] for r in rows],
                             type=_ARROW_TYPES[ANALYSIS_FRAME[c]])
    return pa.table({c: arrays[c] for c in cols})


def frame_pk_sha(rows: list) -> str:
    blob = "\n".join("|".join(str(r[k]) for k in FRAME_PK) for r in rows)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _parquet_bytes(table: pa.Table) -> bytes:
    import io

    buf = io.BytesIO()
    pq.write_table(table, buf, row_group_size=max(1, table.num_rows),
                   **_PARQUET_KW)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Assembly for a single p-level (D1: both files go through the same function body)
# ---------------------------------------------------------------------------
def _assemble_one(p_level: str, inputs, *, in_dept_idx, ego_first_pub: dict,
                  star_fp_by_event: dict, events_by_id: dict,
                  star_by_author: dict, window: int) -> dict:
    triples = dose_unique_triples(inputs.dose[p_level])
    _check_dose_against_events(triples, events_by_id, star_by_author, p_level)

    pk_rows: list = []
    for (inc, star_pid, event_id), d in sorted(triples.items()):
        ev = events_by_id[event_id]
        arrival = int(ev["arrival_year"])
        ego_fp = ego_first_pub.get(inc)
        if ego_fp is None:
            raise FrameAssemblyError(
                f"incumbent {inc!r} has no first-publication year (neither panel nor U1 fallback) — the academic age gap cannot be computed, "
                "never taken as 0 (identity/cohort rule)")
        gap = academic_age_gap({"first_pub_year": ego_fp},
                               {"first_pub_year": star_fp_by_event[event_id]})
        for year in range(arrival - window, arrival + window + 1):
            pk_rows.append({
                "incumbent_person_id": inc, "year": year,
                "star_person_id": star_pid, "event_id": event_id,
                "treated": True, "post": year >= arrival,
                "dose_coupling": float(d["coupling_share"]),
                "dose_low_confidence": bool(d["boundary_sensitive"]),
                "age_gap": float(gap),
            })

    rows, fill_diag = fill_outcomes(pk_rows, inputs.output[p_level],
                                    in_dept_idx.years)
    for r in rows:
        assert_matches_schema(r.keys(), ANALYSIS_FRAME,
                              label=f"analysis_frame_{p_level}")
    rows.sort(key=lambda r: tuple(r[k] for k in FRAME_PK))
    pks = [tuple(r[k] for k in FRAME_PK) for r in rows]
    if len(pks) != len(set(pks)):
        raise FrameAssemblyError(f"{p_level}: frame PK not unique")

    expected = len(triples) * (2 * window + 1)
    assert_invariant_monotone(len(rows), expected,
                              label=f"u6_frame_{p_level}_rows")
    if len(rows) != expected:
        raise FrameAssemblyError(
            f"{p_level}: row count {len(rows)} != triples × window years {expected}")
    return {"rows": rows, "fill_diag": fill_diag, "n_triples": len(triples)}


# ---------------------------------------------------------------------------
# Full assembly (the sole-producer entry point)
# ---------------------------------------------------------------------------
def assemble_frames(inputs, *, out_root, config: dict) -> dict:
    out_root = pathlib.Path(out_root)
    window = int(RED["cohort"]["event_window_years"])
    mnar_thr = float(config["mnar_missing_threshold"])
    provenance = {k: str(config[k]) for k in
                  ("source_snapshot_merkle", "config_sha", "rule_version",
                   "stars_set_hash")}
    for k, v in provenance.items():
        if not v.strip():
            raise ValueError(f"config provenance key {k!r} is empty — stop")

    # --- roster chain (C1) + employed years + pop-min + nt-pool -----------------------------
    members, fold_diag = ir.fold_roster_to_persons(inputs.roster,
                                                   inputs.person_map)
    bridge = ir.bridge_dept_to_inst(inputs.registry)
    in_dept_idx = ir.build_in_dept_index(members, inputs.panel, bridge)
    pool_depts, pool_candidates, nt_diag = ir.never_treated_pool(
        members, inputs.events, bridge)
    dy = ir.distinct_pub_years(inputs.panel)

    events_by_id = inputs.events_by_id()
    star_by_author = inputs.star_by_author()
    star_fp_by_event = star_first_pub_by_event(events_by_id, star_by_author)
    # Fallback robust debut year: gap is a red line and is passed explicitly (a default is never assumed).
    ego_first_pub = first_pub_of_persons(
        inputs.panel, inputs.person_map, inputs.work_first_pub,
        max_leading_gap=RED["academic_age"]["robust_first_pub_max_gap"])

    # --- C rows: empty pool -> CEM shelved (left open); non-empty pool -> CEM with the 4 fixed variables ---------
    c_rows_by_level: dict = {p: [] for p in P_LEVELS}
    cem_status = "skipped_no_pool" if nt_diag["nt_pool_empty"] else "matched"
    # (two-university sample: empty pool; at the 11-university extension, hook cem_match(treated_feats, cand_feats) in here)

    # --- two-file assembly (D1: loop over the same function body) --------------------------------------
    per_level: dict = {}
    for p_level in P_LEVELS:
        per_level[p_level] = _assemble_one(
            p_level, inputs, in_dept_idx=in_dept_idx,
            ego_first_pub=ego_first_pub, star_fp_by_event=star_fp_by_event,
            events_by_id=events_by_id, star_by_author=star_by_author,
            window=window)

    # Same-source assertion for the two tables (D1): byte-identical schema; the single codepath is guaranteed by the loop
    tables = {p: _frame_table(per_level[p]["rows"]) for p in P_LEVELS}
    s01 = tables["p01"].schema.serialize().to_pybytes()
    s05 = tables["p05"].schema.serialize().to_pybytes()
    if s01 != s05:
        raise FrameAssemblyError("D1 破坏: p01/p05 schema 字节级不相同")

    groups_tables: dict = {}
    for p_level in P_LEVELS:
        g_rows = groups_io.build_groups_membership(inputs.dose[p_level],
                                                   c_rows_by_level[p_level])
        garrays = {c: pa.array([r[c] for r in g_rows], type=pa.string())
                   if c != "treated" else
                   pa.array([r[c] for r in g_rows], type=pa.bool_())
                   for c in ("incumbent_person_id", "star_person_id",
                             "event_id", "treated", "control_star_person_id",
                             "matched_treated_event_id")}
        groups_tables[p_level] = pa.table(garrays)

    # --- one COMMIT into the frozen area (same run, physically guaranteed same source) ---------
    payload = {}
    for p_level in P_LEVELS:
        payload[f"analysis_frame_{p_level}.parquet"] = _parquet_bytes(
            tables[p_level])
        payload[f"groups_ABC_{p_level}.parquet"] = _parquet_bytes(
            groups_tables[p_level])
    frame_root = out_root / "frame"
    write_dataset_commit(frame_root, payload,
                         provenance=provenance).stage().commit()

    # --- sidecar (B6-MANIFEST-SIDECAR): row_count + pk_sha256 -----------------
    pk_shas: dict = {}
    for p_level in P_LEVELS:
        rows = per_level[p_level]["rows"]
        pk_shas[p_level] = frame_pk_sha(rows)
        atomic_write_bytes(
            frame_root / f"analysis_frame_{p_level}._manifest.json",
            json.dumps({"row_count": len(rows),
                        "pk_sha256": pk_shas[p_level]},
                       sort_keys=True).encode("utf-8"))

    # --- six-key tally (hand-written; op_id arm honestly N/A, since the derived join has no fetch arm) -------------
    for p_level in P_LEVELS:
        info = per_level[p_level]
        tally = {"stage": f"u6_frame_{p_level}",
                 "expected": info["n_triples"] * (2 * window + 1),
                 "kept": len(info["rows"]), "failed": 0, "skipped": 0,
                 "balanced": True, "op_id_arm": "N/A"}
        assert_matches_schema(tally.keys(), TALLY, label="u6_tally")
        if tally["expected"] != tally["kept"]:
            raise FrameAssemblyError(f"{p_level}: tally does not balance")
        tdir = out_root / "_ledger" / f"u6_frame_{p_level}"
        tdir.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(tdir / "tally.json",
                           json.dumps(tally, sort_keys=True).encode("utf-8"))

    # --- coverage + output_diag sidecars (diagnostics not mixed into TALLY) ---------------------
    violators = {
        p: sorted({r["incumbent_person_id"]
                   for r in groups_tables[p].to_pylist() if r["treated"]
                   and not ir.pop_min_ok(dy.get(r["incumbent_person_id"], 0))})
        for p in P_LEVELS
    }
    # Make events dropped from the frame for zero coupling transparent
    # nominal = events in the events table whose star flag matches the p-level; in frame = events covered by dose triples;
    # difference = events silently dropped from the frame for zero coupling (by mechanism, not a bug, but they must be counted explicitly).
    events_nominal_ids = {
        p: sorted(eid for eid, ev in events_by_id.items()
                  if (star_by_author.get(ev["star_person_id"]) or {})
                  .get(STAR_FLAG_BY_LEVEL[p]))
        for p in P_LEVELS
    }
    events_in_frame_ids = {
        p: sorted({d["event_id"] for d in inputs.dose[p]}) for p in P_LEVELS
    }
    events_dropped = {
        p: sorted(set(events_nominal_ids[p]) - set(events_in_frame_ids[p]))
        for p in P_LEVELS
    }

    coverage = {
        "roster_fold": fold_diag,
        **nt_diag,
        "nt_pool_candidates": pool_candidates,
        "cem_matching": cem_status,
        "in_dept_basis_counts": in_dept_idx.basis_counts,
        "roster_conflict_resolution": in_dept_idx.conflict_diag,
        "events_nominal": {p: len(events_nominal_ids[p]) for p in P_LEVELS},
        "events_in_frame": {p: len(events_in_frame_ids[p]) for p in P_LEVELS},
        "events_dropped_zero_coupling": events_dropped,
        "n_treated_pop_min_violations": {p: len(violators[p])
                                         for p in P_LEVELS},
        "treated_pop_min_violators": violators,
        "pop_min_note": ("D5(#9 人口门槛) 与 C3/T8(treated==dose 三元组) 在已发货"
                         "池上相悖 — 按 HIGH-1 搬运纪律不剔行, 计数人工决定"),
    }
    reports_dir = out_root / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(reports_dir / "coverage_groups.json",
                       json.dumps(coverage, ensure_ascii=False, sort_keys=True,
                                  indent=1).encode("utf-8"))

    na_rates = {p: per_level[p]["fill_diag"]["na_rate_fwci_frac"]
                for p in P_LEVELS}
    verdict_hint = {p: ("HUMAN_REVIEW" if na_rates[p] > mnar_thr else "WARN")
                    for p in P_LEVELS}
    out_diag: dict = {"stage": "u6_assemble",
                      "upstream_mnar_flags": inputs.upstream_diag}
    for p in P_LEVELS:
        out_diag[p] = {**per_level[p]["fill_diag"],
                       "na_robustness_required": na_rates[p] > mnar_thr,
                       "mnar_missing_threshold": mnar_thr}
    atomic_write_bytes(reports_dir / "output_diag.json",
                       json.dumps(out_diag, ensure_ascii=False, sort_keys=True,
                                  indent=1).encode("utf-8"))

    return {
        "n_rows": {p: len(per_level[p]["rows"]) for p in P_LEVELS},
        "n_triples": {p: per_level[p]["n_triples"] for p in P_LEVELS},
        "pk_sha256": pk_shas,
        "na_rate_fwci_frac": na_rates,
        "verdict_hint": verdict_hint,
        "coverage": coverage,
        "frame_root": str(frame_root),
    }
