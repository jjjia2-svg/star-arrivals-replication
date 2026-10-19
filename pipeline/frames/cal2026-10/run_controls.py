#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cal2026-10/run_controls.py — Piece A's CONTROLS: prove the new staging + configs + in-post stage
reproduce the frozen 2026-08-28 objects on the OLD inputs before anything runs on the October
inputs. Repo-authored; runs ONE verbatim-staged legacy script (prodlib build_frame.py, sha-pinned)
inside a staged_run mark and no other ported code; edits no ported file, freezes nothing.

    export SAR_OUT_ROOT=/private/tmp/<empty dir>          # never under a cloud-synced folder
    export SAR_R1_CONFIG=$PWD/config/r1/B0.json           # the run config (R1 F3); unset = STOP
    setup/.venv/bin/python pipeline/frames/cal2026-10/run_controls.py --execute [--econ-smoke]

The C2 shadow reads its event-table root and restake / names tables from the run config's `stage`
section (stage.stage_config(); B0 = October's values), loaded before any control runs.

Controls (each a hard STOP on mismatch — a comparison is never relaxed)
  C1  prodlib on the frozen fnfix inputs (frames_stage.prodlib_config cal=False: the legacy
      08-10 config with only run_dir moved; SSD globs = the mirror at the same path) through
      stage.run_prodlib must reproduce the legacy runs/fnfix frames BYTE for byte (chemistry
      9596b858…, math_stats 03751279…, the files themselves). Same control the 08-28 driver ran
      (BYTE_EQUAL then; this proves the mirror == the data disk for these tables AND that this
      module's runner is the 08-28 runner).
  C1e (review addition, 2026-09-22) the SAME arrangement for economics: the frozen 08-15 config
      econ_fnfix_2026-08-15/config/econ_fnfix.json with only run_dir moved (snapshot copy under
      legacy v2_output/frame_rebuild_2026-07-24/derived_aug, the July u4 _roster_pool ×11,
      registry_v3 and the U3 panel on the data disk — today the mirror at the same path) through
      stage.run_prodlib must reproduce econ_fnfix_2026-08-15/runs/econ_fnfix/data/
      analysis_frame_p01_52ev_topicdose_2026-07-21.csv BYTE for byte (08e5756e…, 26,114 rows,
      35 of 38 events). A missing frozen input is a STOP (NOT_RUN), never a skip: without this
      proof the economics prodlib rung has no control at all, which is where the 09-22 build was.
  C2  the 08-28 event tables through THIS layer's templates + THIS layer's shadow: (i) the
      rendered chemistry / math_stats configs equal frames_stage.prodlib_config(cal=True) key for
      key (labels aside); (ii) the staged shortlist / fnfixbase companions equal
      frames_stage.cal_shortlist / cal_fnfixbase byte for byte; (iii) the produced frames' sha256
      equal the `cal-stage:prodlib <field>` entries of data/cal2026-08-28/frames/
      staging_manifest_2026-08-28.json (the 08-28 prodlib outputs were installed into a scratch
      shadow and are frozen only as those shas).
  C3  inpost_filter on the network-channel rows of the frozen data/frames/p1_frame_econ.csv
      (channel column removed = the prodlib shape), spells = the 920 roster in both id forms via
      the mirror's U2 person map + the 80 persons confirmed on 2026-09-13 (round2_check.json,
      final years) must reproduce data/robustness_2026-09-13_inpost_diag/build_report.json:
      kept == network_inpost, dropped_not_in_post == network_notinpost, dropped_no_spell ==
      network_no_spell. On network ∪ both rows, kept must equal network_inpost + the both-channel
      relations (the diagnostic's both_relations_not_in_post = 0) with the other two unchanged.
  E2  (--econ-smoke, a MEASUREMENT, not a control) the frozen 08-15 econ config with ONLY
      star_first_pub / ego_first_pub switched to works_robust (this layer's econ choice), keyed
      against the frozen econ frame on (incumbent, star, event, year): rows identical / modified
      by column set / removed / added, pairs whose age_gap changes and how many cross the
      run_p1.R |age_gap| <= 60 cut. Caveat written into the report: registry_panel indept consumes
      the panel rows panel_then_wfp caches (prodlib.py:699, :715), so the ego switch also removes
      the panel late-binding from the in-dept index — non-age_gap column diffs belong to that.
  E   (--econ-smoke, not a control — no frozen all-events econ prodlib run exists) the economics
      config on the 08-28 econ table + the October roster + the concatenated supplements runs end
      to end; pool / pairs / rows / per-event coverage are reported, and inpost_filter is then run
      on that frame with the October roster (mirror person map) to report the D2 classes.

MEASURED 2026-09-22 (run of this script, report in $SAR_OUT_ROOT/controls_report.json):
  C1  chemistry BYTE_EQUAL (36,444 lines, 9596b858…), math_stats BYTE_EQUAL (8,163 lines,
      03751279…) — the mirror reproduces the legacy runs/fnfix frames exactly.
  C2  configs EQUAL key for key (both fields); shortlist + fnfixbase companions BYTE_EQUAL to the
      08-28 derivations; frames BYTE_EQUAL to the 08-28 staging-manifest shas (chemistry
      359f270a…, math_stats ca6d75f1…).
  C3  network rows: kept 1,862 / dropped_not_in_post 3,430 / dropped_no_spell 819 == the
      diagnostic; network ∪ both: kept 2,531 = 1,862 + 669 both relations, others unchanged.
  E   econ config on the 08-28 econ table (116 events) + October roster (1,008 rows, 933 pool
      rows after the 75 star exclusions, 24 author ids not in U2 -> outside the pool) + the
      three supplements (19,846 lines): pool 908 persons (1,308 author fragments with edges),
      hop1 6,889 / hop2 9,342, pairs 6,045 (deg1 52, deg2 frozen 576 / unfrozen 5,417), frame
      66,495 rows, 109 of 116 events with pairs (7 structurally empty: A5017960988:2019,
      A5018518935:2003, A5053503664:2023, A5059554264:2021, A5080689800:2024, A5087933968:2020,
      A5102739182:2010); in-post filter with the October roster: kept 2,583 relations /
      dropped_not_in_post 3,462 / dropped_no_spell 0 (D4 by construction, measured), two
      events left with zero network rows (A5017694921:2007, A5059428122:2021). Not a control;
      the October run itself is the frames driver's job (Piece B).
MEASURED 2026-09-22 (review run after the exclusion fix; report in
data/cal2026-10/controls_report_piece_a_review_2026-09-22.json, 105 s):
  C1  unchanged (BYTE_EQUAL both fields).
  C1e econ BYTE_EQUAL (08e5756e…, 26,114 rows; every frozen 08-15 input resolved: snapshot copy in
      legacy derived_aug, July _roster_pool / registry_v3 / U3 panel on the mirror; 43 s).
  C2 / C3 unchanged (EQUAL).
  E   after the fragment rule: exclusion list 1,837 + 187 stars + 92 fragments (21 stars) = 2,043;
      roster pool 1,008 -> 932 rows (76 star rows: the 75 own-id rows + A5038387911, a fragment of
      A5001177483); pool 907 persons; frame 66,495 rows, 109 events, sha 01301641…; keyed against
      the pre-fix smoke frame: 459 rows of 42 persons / 53 events change and ONLY in
      fwci_frac_ex_star / pub_count_ex_star / fwci_mean_ex_star (the fragments' works are now star
      works), 0 rows added or removed; in-post classes unchanged (2,583 / 3,462 / 0).
  E2  the works_robust switch on the frozen 38-event inputs: 13,530 of 26,114 rows change and only
      in age_gap (1,230 of 2,374 pairs; 11 pairs cross |age_gap| <= 60), 0 rows added or removed.
      The economics first-pub rule is therefore a material caliber choice — OPEN for the author.
  Both partition guards in tests/test_verbatim_pipeline.py fail on this directory until its
  files are declared REPO_AUTHORED and tests/pipeline_ported.sha256 is regenerated — the
  integration step's job, same as the sibling cal2026-10 directories.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))
sys.path.insert(0, str(HERE))
import stage                                                            # noqa: E402
import inpost_filter as ipf                                             # noqa: E402
fs08 = stage.fs08

from pipeline.lib.paths import OUT_ROOT_ENV, PathUnresolved             # noqa: E402

STOPS: list[str] = []
REPORT: dict = {}


def stop(msg: str) -> None:
    STOPS.append(msg)
    print(f"\n*** STOP: {msg}", flush=True)


def log(msg: str) -> None:
    print(f"[run_controls] {msg}", flush=True)


def _cfg_core(cfg: dict) -> dict:
    return {k: v for k, v in cfg.items() if k not in ("label", "_cal2026_10_note")}


# ---------------------------------------------------------------------------------------------
# C1
# ---------------------------------------------------------------------------------------------

def econ_frozen_config(run_dir: pathlib.Path) -> dict:
    """The frozen 08-15 econ prodlib config with ONLY run_dir moved — every other path exactly as
    frozen (legacy v2_output copies and the data-disk paths the mirror now serves)."""
    cfg = json.loads((stage.legacy_v2() / stage.ECON_FNFIX / "config" / "econ_fnfix.json")
                     .read_text("utf-8"))
    cfg["run_dir"] = str(run_dir)
    return cfg


def _cfg_inputs(cfg: dict) -> list[str]:
    paths = list(cfg["snapshot"].values()) + [cfg["supplement_jsonl"], cfg["person_map"]["path"],
                                                cfg["events"]["events_dir"],
                                                cfg["events"]["star_set_dir"]]
    paths += list(cfg["roster"]["files"]) + [cfg["indept"]["registry"], cfg["indept"]["panel_glob"]]
    return sorted({p.split("**")[0].rstrip("/") for p in paths})


def _frozen_econ_frame() -> pathlib.Path:
    return stage.legacy_v2() / stage.ECON_FNFIX / "runs" / "econ_fnfix" / "data" / \
        "analysis_frame_p01_52ev_topicdose_2026-07-21.csv"


def control_c1_econ(root: pathlib.Path) -> None:
    mirror = root / "c1_fnfix_econ"
    cfg = econ_frozen_config(mirror / "runs" / "econ_fnfix")
    rep = REPORT.setdefault("c1", {}).setdefault("econ", {})
    rep["frozen_config"] = str(stage.legacy_v2() / stage.ECON_FNFIX / "config" / "econ_fnfix.json")
    missing = [q for q in _cfg_inputs(cfg) if not os.path.exists(q)]
    rep["inputs_missing"] = missing
    if missing:
        rep["result"] = "NOT_RUN"
        stop(f"C1e econ: frozen 08-15 inputs missing on this machine: {missing}")
        return
    out = stage.run_prodlib("econ", mirror, cfg, rep)
    frozen = _frozen_econ_frame()
    equal = out.read_bytes() == frozen.read_bytes()
    rep.update({"frozen": str(frozen), "frozen_sha256": stage.sha(frozen),
                "result": "BYTE_EQUAL" if equal else "NOT_EQUAL"})
    log(f"C1e econ: {'BYTE_EQUAL' if equal else 'NOT_EQUAL'}")
    if not equal:
        acc = fs08.keyed_csv_accounting(frozen, out, ("incumbent_person_id", "star_person_id",
                                                      "event_id", "year"))
        rep["accounting"] = {k: (v if k != "modified" else v[:20]) for k, v in acc.items()}
        stop("C1e econ: prodlib on the frozen 08-15 inputs is not byte-equal to the legacy econ frame")


def control_c1(root: pathlib.Path) -> None:
    v2 = stage.legacy_v2()
    for field in stage.FIELDS_GOLD:
        mirror = root / f"c1_fnfix_{field}"
        cfg = fs08.prodlib_config(field, mirror, mirror / "runs" / field, cal=False)
        out = stage.run_prodlib(field, mirror, cfg, REPORT.setdefault("c1", {}).setdefault(field, {}))
        frozen = v2 / stage.GOLD / "runs" / "fnfix" / field / "data" / \
            "analysis_frame_p01_52ev_topicdose_2026-07-21.csv"
        equal = out.read_bytes() == frozen.read_bytes()
        REPORT["c1"][field].update({"frozen": str(frozen), "frozen_sha256": stage.sha(frozen),
                                    "result": "BYTE_EQUAL" if equal else "NOT_EQUAL"})
        log(f"C1 {field}: {'BYTE_EQUAL' if equal else 'NOT_EQUAL'}")
        if not equal:
            stop(f"C1 {field}: prodlib on the frozen fnfix inputs is not byte-equal to the legacy frame")


# ---------------------------------------------------------------------------------------------
# C2
# ---------------------------------------------------------------------------------------------

def control_c2(root: pathlib.Path, stage_cfg: dict) -> pathlib.Path:
    v2 = stage.legacy_v2()
    shadow_root = root / "shadow_cal0828"
    sh, rec = stage.build_shadow(shadow_root, events="cal2026-08-28", stage_cfg=stage_cfg)
    REPORT["c2"] = {"shadow_entries": len(sh.entries), "derivation": rec, "fields": {}}
    (root / "staging_manifest_c2.json").write_text(
        json.dumps({"entries": sh.manifest(), "derivation": rec}, ensure_ascii=False, indent=1,
                   default=str), encoding="utf-8")
    sm = json.loads((stage.CAL08 / "frames" / "staging_manifest_2026-08-28.json").read_text("utf-8"))
    want = {e["origin"].split()[-1]: e["sha256"] for e in sm["entries"]
            if e["origin"].startswith("cal-stage:prodlib ")}
    gold = shadow_root / "v2_output" / stage.GOLD / "data"
    comp = {"shortlist": gold.joinpath("shortlist_fnfix.csv").read_bytes() == fs08.cal_shortlist(v2)}
    for field in stage.FIELDS_GOLD:
        comp[f"fnfixbase_{field}"] = gold.joinpath(
            f"events_{field}_fnfixbase_2026-08-10.csv").read_bytes() == fs08.cal_fnfixbase(v2, field)
    REPORT["c2"]["companions_byte_equal_to_08_28"] = comp
    for k, ok in comp.items():
        log(f"C2 companion {k}: {'BYTE_EQUAL' if ok else 'NOT_EQUAL'}")
        if not ok:
            stop(f"C2: staged companion {k} differs from the 08-28 derivation")
    for field in stage.FIELDS_GOLD:
        mirror = root / f"c2_cal0828_{field}"
        run_dir = mirror / "runs" / field
        cfg = stage.render_config(field, shadow_root, run_dir)
        ref = fs08.prodlib_config(field, shadow_root, run_dir, cal=True)
        cfg_equal = _cfg_core(cfg) == _cfg_core(ref)
        diff = {k: (cfg.get(k), ref.get(k)) for k in set(cfg) | set(ref)
                if k not in ("label", "_cal2026_10_note") and cfg.get(k) != ref.get(k)}
        rep = REPORT["c2"]["fields"].setdefault(field, {})
        rep["config_equal_to_08_28"] = cfg_equal
        if not cfg_equal:
            rep["config_diff"] = diff
            stop(f"C2 {field}: rendered config differs from frames_stage.prodlib_config(cal=True): "
                 f"{sorted(diff)}")
            continue
        out = stage.run_prodlib(field, mirror, cfg, rep)
        got = stage.sha(out)
        rep.update({"want_sha256_from_08_28_staging_manifest": want.get(field),
                    "result": "BYTE_EQUAL" if got == want.get(field) else "NOT_EQUAL"})
        log(f"C2 {field}: config {'EQUAL' if cfg_equal else 'DIFF'}, frame "
            f"{'BYTE_EQUAL' if got == want.get(field) else 'NOT_EQUAL'} ({got[:12]} vs "
            f"{(want.get(field) or '?')[:12]})")
        if got != want.get(field):
            stop(f"C2 {field}: prodlib frame sha {got} != 08-28 staging manifest {want.get(field)}")
    return shadow_root


# ---------------------------------------------------------------------------------------------
# C3
# ---------------------------------------------------------------------------------------------

def _prodlib_shaped(src: pathlib.Path, channels: set[str], out: pathlib.Path) -> dict:
    """The frozen union frame's rows with channel in `channels`, channel column removed — the
    shape prodlib's output has (CRLF like prodlib's csv.writer)."""
    n = 0
    with open(src, newline="", encoding="utf-8") as fi, open(out, "w", newline="",
                                                             encoding="utf-8") as fo:
        r = csv.reader(fi)
        hdr = next(r)
        ic = hdr.index("channel")
        w = csv.writer(fo)
        w.writerow([c for i, c in enumerate(hdr) if i != ic])
        for row in r:
            if row[ic] in channels:
                w.writerow([c for i, c in enumerate(row) if i != ic])
                n += 1
    return {"source": str(src), "source_sha256": stage.sha(src), "channels": sorted(channels),
            "rows": n, "out": str(out)}


def control_c3(root: pathlib.Path) -> None:
    diag = json.loads((REPO / "data" / "robustness_2026-09-13_inpost_diag" / "build_report.json")
                      .read_text("utf-8"))
    want = diag["relations_by_class"]
    d = root / "c3_inpost"
    d.mkdir()
    # the 102-person verification record is not shipped (restricted deposit): control C3 is author-only
    r2 = json.loads((REPO / "data" / "roster_verify_2026-09-13_network102" / "round2_check.json")
                    .read_text("utf-8"))
    conf = [(pid, c["final_year_start"], c["final_year_end"]) for pid, c in r2.items()
            if c["final_verdict"] == "confirmed"]
    assert len(conf) == diag["spells"]["confirmed_2026_09_13"], len(conf)
    extra = d / "confirmed_spells.csv"
    with open(extra, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["pid", "year_start", "year_end"])
        w.writerows(conf)
    pm = stage.derived_root() / "u2_person_map_11school_2026-07-16" / "person_map" / "data.parquet"
    roster = REPO / "data" / "raw_verified" / "roster_econ_verified.parquet"
    spells, sources = ipf.spells_from_roster(roster, pm, identity=False)
    sources["extra"] = ipf.spells_from_csv(extra, spells)
    frame = REPO / "data" / "frames" / "p1_frame_econ.csv"
    REPORT["c3"] = {"diag_relations_by_class": want, "frame": str(frame),
                    "frame_sha256": stage.sha(frame)}
    # network rows only -> the diagnostic's three network classes
    shaped = _prodlib_shaped(frame, {"network"}, d / "p1_econ_network_only.csv")
    rep = ipf.run(d / "p1_econ_network_only.csv", spells, sources, d / "network_only_inpost.csv",
                  d / "network_only_report.json")
    got = rep["relations_by_class"]
    ok = (got["kept"] == want["network_inpost"] and
          got["dropped_not_in_post"] == want["network_notinpost"] and
          got["dropped_no_spell"] == want["network_no_spell"])
    REPORT["c3"]["network_only"] = {"input": shaped, "relations_by_class": got,
                                    "rows_by_class": rep["rows_by_class"],
                                    "result": "EQUAL" if ok else "NOT_EQUAL"}
    log(f"C3 network-only: {got} vs diag {want} -> {'EQUAL' if ok else 'NOT_EQUAL'}")
    if not ok:
        stop("C3: the in-post filter does not reproduce the 2026-09-13 diagnostic's classes")
    # network ∪ both rows -> kept grows by exactly the both relations
    import duckdb                                                      # noqa: PLC0415
    con = duckdb.connect()
    n_both = con.execute(f"SELECT count(DISTINCT incumbent_person_id || '|' || event_id) FROM "
                         f"read_csv_auto('{frame.as_posix()}') WHERE channel = 'both'").fetchone()[0]
    con.close()
    shaped2 = _prodlib_shaped(frame, {"network", "both"}, d / "p1_econ_network_both.csv")
    rep2 = ipf.run(d / "p1_econ_network_both.csv", spells, sources, d / "network_both_inpost.csv",
                   d / "network_both_report.json")
    got2 = rep2["relations_by_class"]
    ok2 = (got2["kept"] == want["network_inpost"] + n_both and
           got2["dropped_not_in_post"] == want["network_notinpost"] and
           got2["dropped_no_spell"] == want["network_no_spell"] and
           diag["both_relations_not_in_post_by_spells"] == 0)
    REPORT["c3"]["network_and_both"] = {"input": shaped2, "both_relations": n_both,
                                        "relations_by_class": got2,
                                        "result": "EQUAL" if ok2 else "NOT_EQUAL"}
    log(f"C3 network∪both: {got2}, both relations {n_both} -> {'EQUAL' if ok2 else 'NOT_EQUAL'}")
    if not ok2:
        stop("C3: network ∪ both rows do not add exactly the both-channel relations to kept")


# ---------------------------------------------------------------------------------------------
# E2 (measurement: the econ first-pub mode switch on the frozen inputs)
# ---------------------------------------------------------------------------------------------

def measure_e2(root: pathlib.Path) -> None:
    mirror = root / "e2_fp_modes"
    cfg = econ_frozen_config(mirror / "runs" / "econ_fnfix_fpmodes")
    rep = REPORT.setdefault("e2_first_pub_modes", {
        "what": "frozen 08-15 econ config with star_first_pub and ego_first_pub = works_robust "
                "(the cal2026-10 econ choice) vs the frozen econ frame; a measurement, not a control",
        "caveat": "registry_panel indept consumes the panel rows panel_then_wfp caches "
                  "(prodlib.py:699, :715); with ego works_robust that cache is empty, so the in-dept "
                  "index loses its panel late-binding too — non-age_gap diffs belong to that"})
    missing = [q for q in _cfg_inputs(cfg) if not os.path.exists(q)]
    if missing:
        rep["result"] = "NOT_RUN"
        rep["inputs_missing"] = missing
        log(f"E2: not run, frozen inputs missing: {missing}")
        return
    cfg["star_first_pub"] = {"mode": "works_robust"}
    cfg["ego_first_pub"] = {"mode": "works_robust"}
    out = stage.run_prodlib("econ", mirror, cfg, rep)
    frozen = _frozen_econ_frame()
    acc = fs08.keyed_csv_accounting(frozen, out, ("incumbent_person_id", "star_person_id",
                                                  "event_id", "year"), float_cols=("age_gap",))
    by_cols: dict = {}
    gap_pairs: dict = {}
    for m in acc["modified"]:
        by_cols[",".join(m["cols"])] = by_cols.get(",".join(m["cols"]), 0) + 1
        if "age_gap" in m["cols"]:
            k = (m["key"][0], m["key"][2])
            gap_pairs[k] = (float(m["frozen"]["age_gap"]), float(m["new"]["age_gap"]))
    cross = [k for k, (a, b) in gap_pairs.items() if (abs(a) <= 60) != (abs(b) <= 60)]
    rep.update({"rows_frozen": acc["rows_frozen"], "rows_new": acc["rows_new"],
                "rows_identical": acc["identical"], "rows_modified": len(acc["modified"]),
                "rows_removed": len(acc["removed"]), "rows_added": len(acc["added"]),
                "modified_by_column_set": by_cols,
                "pairs_with_age_gap_changed": len(gap_pairs),
                "pairs_crossing_abs60": len(cross),
                "age_gap_change_examples": [{"pair": list(k), "frozen": a, "new": b}
                                            for k, (a, b) in sorted(gap_pairs.items())[:10]],
                "result": "MEASURED"})
    log(f"E2: rows identical {acc['identical']} / modified {len(acc['modified'])} "
        f"(by cols {by_cols}) / removed {len(acc['removed'])} / added {len(acc['added'])}; "
        f"pairs with age_gap changed {len(gap_pairs)}, crossing |60| {len(cross)}")


# ---------------------------------------------------------------------------------------------
# E (smoke)
# ---------------------------------------------------------------------------------------------

def econ_smoke(root: pathlib.Path, shadow_root: pathlib.Path) -> None:
    mirror = root / "e_econ_smoke"
    cfg = stage.render_config("econ", shadow_root, mirror / "runs" / "econ")
    rep = REPORT.setdefault("econ_smoke", {})
    try:
        out = stage.run_prodlib("econ", mirror, cfg, rep)
    except Exception as e:                                             # noqa: BLE001
        rep["error"] = repr(e)[:2000]
        stop(f"E econ smoke: prodlib raised {repr(e)[:300]}")
        return
    pm = stage.derived_root() / "u2_person_map_11school_2026-07-16" / "person_map" / "data.parquet"
    roster = stage.CAL10 / "roster_econ_verified_2026-10.parquet"
    spells, sources = ipf.spells_from_roster(roster, pm, identity=False)
    r = ipf.run(out, spells, sources, mirror / "inpost" / "frame_inpost.csv",
                mirror / "inpost" / "inpost_report.json")
    rep["inpost"] = {k: r[k] for k in ("relations_by_class", "rows_by_class", "persons_by_class",
                                       "events_left_with_zero_rows")}
    pe = rep['prodlib']['econ']
    log(f"E econ smoke: frame {pe['frame_lines']} lines, pool {pe['build_report']['pool']}, "
        f"export {pe['build_report']['export']['n_events_in_frame']} events in frame, "
        f"in-post {rep['inpost']['relations_by_class']}")


# ---------------------------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true", help="required: several prodlib runs (minutes)")
    ap.add_argument("--econ-smoke", action="store_true", help="also run the economics config once")
    args = ap.parse_args(argv)
    if not args.execute:
        print("Runs prodlib four to five times against the data mirror (minutes). Re-run with "
              "--execute.", file=sys.stderr)
        return 2
    out_root = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not out_root:
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute directory under /private/tmp")
    root = pathlib.Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be empty: {root}")
    stage_cfg = stage.stage_config()                   # $SAR_R1_CONFIG unset = STOP, before any control
    REPORT.update({"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                   "authority": "the author's design record of 2026-09-22 (private archive)",
                   "piece": "A (configs + in-post stage + controls)",
                   "derived_root": str(stage.derived_root())})
    t0 = time.time()
    log("C1: prodlib on the frozen fnfix inputs")
    control_c1(root)
    log("C1e: prodlib on the frozen 08-15 econ inputs")
    control_c1_econ(root)
    log("C2: the 08-28 tables through the cal2026-10 templates + shadow")
    shadow_root = control_c2(root, stage_cfg)
    log("C3: the in-post filter against the 2026-09-13 diagnostic")
    control_c3(root)
    if args.econ_smoke and not STOPS:
        log("E: economics config smoke run")
        econ_smoke(root, shadow_root)
        log("E2: the econ first-pub mode switch on the frozen 08-15 inputs (measurement)")
        measure_e2(root)
    REPORT["stops"] = STOPS
    REPORT["total_secs"] = round(time.time() - t0, 1)
    (root / "controls_report.json").write_text(
        json.dumps(REPORT, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    log(f"{'ALL CONTROLS PASSED' if not STOPS else str(len(STOPS)) + ' STOP(s)'} — report "
        f"{root / 'controls_report.json'}")
    return 0 if not STOPS else 1


if __name__ == "__main__":
    raise SystemExit(main())
