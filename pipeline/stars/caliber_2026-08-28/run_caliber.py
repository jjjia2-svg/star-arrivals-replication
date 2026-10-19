#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""caliber_2026-08-28/run_caliber.py — Task-1 driver: the author-signed caliber (D-A, D-B + the five
personnel rulings) turned into the new candidate verdicts and event tables. Repo-authored launcher
(declared in `pipeline.lib.paths.LAUNCHERS`); it edits NO ported file and NO frozen artifact — all
frozen inputs are read from the read-only legacy tree, all products land in `data/cal2026-08-28/`.

    export SAR_OUT_ROOT=/private/tmp/<empty dir>       # scratch, NEVER under ~/Documents
    python3 "pipeline/stars/caliber_2026-08-28/run_caliber.py" --execute

Phases (each measured, each with a hard STOP on any surprise):

  P  drive the PORTED `72_restake_fnfix_stars.py` through the run_stars staging machinery for the
     5 machine-relevant candidates (A5027778630, A5091826237, A5017222669, A5090916445 + A5062352558 as the zero-effect
     control for her 24th call), with the calls table = frozen 385 rows + the 6 signed exclusions.
  E  the caliber-layer equivalent machine (`restake_equiv.py`):
       E1 PROOF — frozen 67-row inputs, no overrides, on 5 proof candidates
          (A5018518935, A5006190609, A5035138469, A5074090421 + A5062352558): rows must be byte-identical to the frozen
          `fnfix_restake_2026-08-15.csv` lines.
       E2 CAL — the 5 candidates of phase P with the dossier first_pub anchors injected
          (A5091826237 1983 → bin 14-17 is the one row the ported machine cannot produce).
  V  the full 71-row verdict set (frozen 67 + 4 new) under `caliber.gate_age` × `caliber.in_window`
     × the machine's `after_pass`; candidate-level diff against the OLD caliber must be exactly
     {A5044432173 out, A5062352558 in} plus the 4 new admissions — anything else STOPS the run.
  F  freeze: candidates/restake/verdicts/event tables + MANIFEST into `data/cal2026-08-28/`.

A5091826237's outcome is whatever E2 returns — recorded either way, with the number.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import runpy
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))

from pipeline.lib.paths import (OUT_ROOT_ENV, PathUnresolved, legacy_thesis,  # noqa: E402
                                output_target, require_readable, staged_run)

sys.path.insert(0, str(HERE))
import caliber                    # noqa: E402
import cleaned_works              # noqa: E402
import restake_equiv              # noqa: E402

GOLD = "multidisc_gold_2026-08-10"
CAL_DIR = REPO / "data" / "cal2026-08-28"

#: the four author-signed admissions (register rulings 1-4), in ruling order, plus A5062352558 (ruling 5)
#: as the measured zero-effect control for her 24th call.
NEW_IDS = ["A5027778630", "A5091826237", "A5017222669", "A5090916445"]
A5062352558_ID = "A5062352558"
A5044432173_ID = "A5044432173"
#: E1 proof candidates: >=3 untouched by the 2026-08-28 cleanups (A5018518935, A5006190609, A5035138469, A5074090421 — econ
#: path x2 incl. a U4flagged9 literal row, one math and one chem candidate whose frozen drops moved
#: their bins, so the drop machinery is exercised) + A5062352558 (heavy drops; touched, but E1 runs the
#: FROZEN inputs where she is as-frozen).
PROOF_IDS = ["A5018518935", "A5006190609", "A5035138469", "A5074090421", A5062352558_ID]

STOPS: list[str] = []


def _stop(msg: str) -> None:
    STOPS.append(msg)
    print(f"\n*** STOP: {msg}", flush=True)


def _sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _read_csv(p: pathlib.Path) -> list[dict]:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _legacy_gold() -> pathlib.Path:
    return pathlib.Path(str(require_readable(legacy_thesis() / "v2_output" / GOLD)))


def build_new_candidate_rows() -> list[dict]:
    """The 4 admitted candidates' rows, built by the SAME rules the recovered builders used
    (school from the CHECK table's depts, name/arrival/post from the human recheck table) —
    machine-derived, not hand-typed. Only the admission itself is data
    (`data/cal2026-08-28/new_candidates_2026-08-28.csv`, author-signed)."""
    gold = _legacy_gold()
    admitted = _read_csv(CAL_DIR / "new_candidates_2026-08-28.csv")
    assert [r["author_id"] for r in admitted] == NEW_IDS, "admission table order drifted"
    recheck, check = {}, {}
    for f in ("chemistry", "math_stats"):
        for r in _read_csv(gold / "data" / f"poach_fn_recheck_{f}_2026-08-15.csv"):
            recheck[r["author_id"]] = r
        for r in _read_csv(gold / "data" / f"poach_fn_CHECK_{f}.csv"):
            check[r["author_id"]] = r
    rows = []
    for a in admitted:
        aid = a["author_id"]
        rc, ck = recheck[aid], check[aid]
        assert rc["verdict"] == "wrong_year_out_of_window", (aid, rc["verdict"])
        school = ck["depts"].split(";")[0].replace("_chem", "").replace("_mathstats", "")
        rows.append({"author_id": aid, "name": rc["name"], "field": a["field"], "school": school,
                     "arrival_true": rc["arrival_true"], "arrival_roster": ck["arrival_roster"],
                     "in_window": caliber.in_window(rc["arrival_true"]),
                     "post_at_arrival": rc["post_at_arrival"][:80]})
    return rows


def _write_dict_csv(path: pathlib.Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def phase_ported(run_root: pathlib.Path, cand_rows: list[dict], calls_text: str) -> dict[str, str]:
    """Phase P: stage and run the ported `72` exactly the way `run_stars.py` does."""
    spec = importlib.util.spec_from_file_location("sar_run_stars", REPO / "pipeline/stars/run_stars.py")
    rs = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = rs               # dataclass introspection needs the registered module
    spec.loader.exec_module(rs)
    os.environ[OUT_ROOT_ENV] = str(run_root)
    for line in rs._preimport_screening():
        print(f"[run_caliber] ranking machine {line}")
    run_dir = output_target(rs.SCRATCH, "caliber_2026-08-28 ported-72 restake") / GOLD
    ported = REPO / "pipeline/stars" / GOLD / "code" / "72_restake_fnfix_stars.py"
    target = run_dir / "code" / ported.name
    print(f"[run_caliber] P: run directory -> {run_dir}")
    print(f"[run_caliber] staged {ported.relative_to(REPO)} ({rs._link(ported, target)})")
    cols = ["author_id", "name", "field", "school", "arrival_true", "arrival_roster",
            "in_window", "post_at_arrival"]
    _write_dict_csv(run_dir / "data" / "fnfix_candidates_restake.csv", cand_rows, cols)
    (run_dir / "verify").mkdir(parents=True, exist_ok=True)
    (run_dir / "verify" / "fnfix_work_level_calls.csv").write_text(calls_text, encoding="utf-8")
    sys.argv = [str(target)]
    os.environ.setdefault("PYTHONHASHSEED", "0")
    t0 = time.time()
    with staged_run(target):
        runpy.run_path(str(target), run_name="__main__")
    out = run_dir / "data" / "fnfix_restake_2026-08-15.csv"
    print(f"[run_caliber] P finished in {time.time() - t0:.1f} s -> {out} ({out.stat().st_size} B)")
    return restake_equiv.csv_lines_by_author(out)


def calls_text_with_exclusions(frozen_calls: pathlib.Path) -> tuple[str, set, set]:
    """The frozen 385-row calls file + the 6 signed exclusion rows, and both drop sets."""
    text = frozen_calls.read_bytes().decode("utf-8")   # bytes: keep the \r\n endings
    if not text.endswith("\n"):
        text += "\n"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["author_id", "work_id", "is_mine", "reason"])
    for r in cleaned_works.exclusion_rows_for_72():
        w.writerow(r)
    frozen_pairs = {(r["author_id"], r["work_id"]) for r in _read_csv(frozen_calls)
                    if r["is_mine"].strip().lower() == "false"}
    new_pairs = frozen_pairs | cleaned_works.exclusions()
    return text + buf.getvalue(), frozen_pairs, new_pairs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--execute", action="store_true",
                    help="required: two full snapshot rankings plus pool builds (minutes, data disk)")
    args = ap.parse_args(argv)
    if not args.execute:
        print("This runs the 24 GB snapshot ranking machine several times (minutes, needs the data "
              "disk). Re-run with --execute.", file=sys.stderr)
        return 2
    out_root = os.environ.get(OUT_ROOT_ENV, "").strip()
    if not out_root:
        raise PathUnresolved(f"set ${OUT_ROOT_ENV} to an empty absolute directory under /private/tmp")
    out_root = pathlib.Path(out_root)
    if any(out_root.iterdir()):
        raise PathUnresolved(f"${OUT_ROOT_ENV} must be empty: {out_root}")
    report: dict = {"generated": datetime.datetime.now().isoformat(timespec="seconds"),
                    "authority": "the author's decision record of 2026-08-28 (private archive)"}
    gold = _legacy_gold()
    frozen_cands_p = gold / "data" / "fnfix_candidates_restake.csv"
    frozen_restake_p = gold / "data" / "fnfix_restake_2026-08-15.csv"
    frozen_calls_p = gold / "verify" / "fnfix_work_level_calls.csv"
    report["frozen_inputs_sha256"] = {p.name: _sha(p) for p in
                                      (frozen_cands_p, frozen_restake_p, frozen_calls_p)}
    frozen_cands = _read_csv(frozen_cands_p)
    frozen_restake_lines = restake_equiv.csv_lines_by_author(frozen_restake_p)
    frozen_restake = _read_csv(frozen_restake_p)
    assert len(frozen_cands) == 67 and len(frozen_restake) == 67

    # ---- machine candidates: the 4 admissions + A5062352558 (zero-effect control) ---------------------
    new_rows = build_new_candidate_rows()
    a5062352558_row = next(r for r in frozen_cands if r["author_id"] == A5062352558_ID)
    run_cands = new_rows + [a5062352558_row]
    calls_text, frozen_pairs, new_pairs = calls_text_with_exclusions(frozen_calls_p)
    report["drops"] = {"frozen": len(frozen_pairs), "cal2026-08-28": len(new_pairs)}
    print(f"[run_caliber] drops: frozen {len(frozen_pairs)} -> cal {len(new_pairs)}")

    # ---- phase P: the ported 72 -----------------------------------------------------------------
    (out_root / "ported72").mkdir()
    ported_lines = phase_ported(out_root / "ported72", run_cands, calls_text)
    report["ported72_rows"] = list(ported_lines.values())

    # ---- phase E: the equivalence machine -------------------------------------------------------
    t0 = time.time()
    con = restake_equiv.connect(out_root / "equiv_duck_tmp")
    n_aw = restake_equiv.load_aw_raw(con)
    print(f"[run_caliber] E: aw_raw {n_aw:,} rows in {time.time() - t0:.1f} s")
    report["aw_raw_rows"] = n_aw

    # E1 proof: frozen inputs, no overrides — must be byte-identical to the frozen restake rows
    proof_cands = [r for r in frozen_cands if r["author_id"] in PROOF_IDS]
    proof_csv = out_root / "equiv_proof.csv"
    restake_equiv.restake(con, proof_cands, frozen_pairs, proof_csv)
    proof_lines = restake_equiv.csv_lines_by_author(proof_csv)
    proof_ok = {}
    for aid in PROOF_IDS:
        proof_ok[aid] = proof_lines[aid] == frozen_restake_lines[aid]
        if not proof_ok[aid]:
            _stop(f"E1 equivalence proof FAILED for {aid}:\n  frozen: {frozen_restake_lines[aid]}\n"
                  f"  equiv : {proof_lines[aid]}")
    report["equiv_proof"] = {aid: ("byte-identical" if ok else "MISMATCH")
                            for aid, ok in proof_ok.items()}
    print(f"[run_caliber] E1 proof: {sum(proof_ok.values())}/{len(PROOF_IDS)} byte-identical")

    # E2 cal: the 5 machine candidates, new drops, dossier first_pub anchors injected
    overrides = cleaned_works.first_pub_overrides()
    cal_csv = out_root / "equiv_cal.csv"
    restake_equiv.restake(con, run_cands, new_pairs, cal_csv, overrides=overrides)
    cal_lines = restake_equiv.csv_lines_by_author(cal_csv)
    cal_rows = {r["author_id"]: r for r in _read_csv(cal_csv)}
    con.close()

    # cross-checks: A5062352558 byte-identical to frozen; non-A5091826237 machine rows equal ported's
    if cal_lines[A5062352558_ID] != frozen_restake_lines[A5062352558_ID]:
        _stop(f"A5062352558's 24th call was NOT zero-effect:\n  frozen: {frozen_restake_lines[A5062352558_ID]}\n"
              f"  cal   : {cal_lines[A5062352558_ID]}")
    if ported_lines[A5062352558_ID] != frozen_restake_lines[A5062352558_ID]:
        _stop("A5062352558's ported-72 row differs from her frozen row")
    for aid in NEW_IDS:
        if aid == "A5091826237":
            continue                      # A5091826237: the anchored bin is the one row 72 cannot produce
        if cal_lines[aid] == ported_lines[aid]:
            continue
        # the ONE difference the anchor is allowed to make without a bin change: the aage column
        # (and its explanatory note). Ranking fields must be identical to the ported machine's.
        p = next(csv.reader([ported_lines[aid]]))
        c = next(csv.reader([cal_lines[aid]]))
        anchored = cleaned_works.aage(aid, c[4])
        if (p[:14] == c[:14] and c[15] == str(anchored)
                and c[14].startswith("first_pub_override=")):
            print(f"[run_caliber] {aid}: ported aage {p[15]} -> anchored {c[15]} (same bin, "
                  f"ranking fields identical) — the dossier injection, documented in the note")
            continue
        _stop(f"equiv vs ported mismatch for {aid}:\n  ported: {ported_lines[aid]}\n"
              f"  equiv : {cal_lines[aid]}")
    report["A5091826237"] = {"ported_native_row": ported_lines["A5091826237"],
                      "equiv_anchored_row": cal_lines["A5091826237"]}

    # ---- phase V: the 71-row verdict set --------------------------------------------------------
    cand_by_id = {r["author_id"]: r for r in frozen_cands}
    for r in new_rows:
        cand_by_id[r["author_id"]] = r
    verdict_rows, flips = [], []
    all_rows = frozen_restake + [cal_rows[a] for a in NEW_IDS]
    for r in all_rows:
        aid = r["author_id"]
        is_new = aid in NEW_IDS
        ga = caliber.gate_age(r["aage"])
        iw = caliber.in_window(r["arrival_true"])
        ev = caliber.event_verdict(after_pass=r["after_pass"], aage=r["aage"],
                                   arrival_true=r["arrival_true"])
        old_ev = (False if is_new else caliber.old_event_verdict_fnfix(
            after_pass=r["after_pass"], field=r["field"],
            in_window_flag=cand_by_id[aid].get("in_window")))
        reason = ("" if ev else
                  "; ".join(x for x in (
                      "" if caliber.restake_pass(r["after_pass"]) else f"restake_fail({r['after_pct']})",
                      "" if ga else f"D-A gate_age fail (aage={r['aage']})",
                      "" if iw else f"D-B window fail (arrival_true={r['arrival_true']})") if x))
        if not is_new and ev != old_ev:
            flips.append((aid, r["name"], "in" if ev else "out"))
        verdict_rows.append({"author_id": aid, "name": r["name"], "field": r["field"],
                             "school": r["school"], "arrival_true": r["arrival_true"],
                             "after_pct": r["after_pct"], "after_pass": r["after_pass"],
                             "aage": r["aage"], "gate_age": ga, "in_window": iw,
                             "event_cal2026_08_28": ev, "new_candidate_2026_08_28": is_new,
                             "reason_if_out": reason})
    expected_flips = {(A5044432173_ID, "out"), (A5062352558_ID, "in")}
    got_flips = {(a, d) for a, _, d in flips}
    if got_flips != expected_flips:
        _stop(f"candidate-level diff is NOT exactly {{A5044432173 out, A5062352558 in}}: {flips}")
    new_pass = {a: caliber.event_verdict(after_pass=cal_rows[a]["after_pass"],
                                         aage=cal_rows[a]["aage"],
                                         arrival_true=cal_rows[a]["arrival_true"])
                for a in NEW_IDS}
    for aid in NEW_IDS:
        if aid != "A5091826237" and not new_pass[aid]:
            _stop(f"unexpected restake failure for admitted candidate {aid} "
                  f"(register expected a flat pass): {cal_lines[aid]}")
    report["new_candidate_verdicts"] = {aid: cal_lines[aid] for aid in NEW_IDS}
    report["A5091826237"]["passes"] = new_pass["A5091826237"]

    # ---- events + diff --------------------------------------------------------------------------
    frames_econ = REPO / "data" / "frames" / "p1_events_ledger_econ.csv"
    rv = REPO / "data" / "raw_verified"
    econ_lines = [ln for ln in frames_econ.read_bytes().decode("utf-8").split("\n") if ln]
    econ_keep = [ln for ln in econ_lines[1:] if ln.split(",")[1] != A5044432173_ID]
    if len(econ_keep) != len(econ_lines) - 2:
        _stop(f"econ ledger: expected exactly one A5044432173 row removed, "
              f"got {len(econ_lines) - 1 - len(econ_keep)}")
    events = {}
    events["econ"] = econ_lines[0] + "\n" + "\n".join(econ_keep) + "\n"

    sig = "human_web_verified_dossier_2026-08-27_author_signed_2026-08-28"
    admitted = {r["author_id"]: r for r in _read_csv(CAL_DIR / "new_candidates_2026-08-28.csv")}
    wide_extra = (gold / "data" / "fnfix_new_events_wide_extra.csv").read_bytes().decode("utf-8")
    a5062352558_event_line = [ln for ln in wide_extra.split("\n") if ln][1]

    def event_line(aid: str) -> str:
        """One full CSV line, \r\n-terminated like every line of the frozen fnfix event tables."""
        c, a = cand_by_id[aid], admitted[aid]
        buf = io.StringIO()
        csv.writer(buf).writerow([c["field"], c["school"], aid, c["name"], c["arrival_true"],
                                  a["evidence_grade"], a["evidence_url"], sig])
        return buf.getvalue()

    chem_add = [event_line("A5027778630")]                       # ruling 1: A5027778630
    if new_pass["A5091826237"]:
        chem_add.append(event_line("A5091826237"))               # ruling 2: A5091826237, machine-conditional
    chem_add.append(a5062352558_event_line + "\n")                     # ruling 5: A5062352558, frozen row verbatim
    math_add = [event_line("A5017222669"), event_line("A5090916445")]   # rulings 3-4
    for field, frozen_name, extra in (("chemistry", "events_chemistry_fnfix.csv", chem_add),
                                      ("math_stats", "events_math_stats_fnfix.csv", math_add)):
        text = (rv / frozen_name).read_bytes().decode("utf-8")
        if not text.endswith("\n"):
            text += "\n"
        events[field] = text + "".join(extra)

    # window check on EVERY event of the new tables (D-B consumed everywhere)
    for field, key, col in (("econ", "econ", "arrival_year"),
                            ("chemistry", "chemistry", "arrival_corrected"),
                            ("math_stats", "math_stats", "arrival_corrected")):
        rows = list(csv.DictReader(io.StringIO(events[key])))
        bad = [r for r in rows if not caliber.in_window(r[col])]
        if bad:
            _stop(f"{field}: {len(bad)} event(s) outside the uniform window: "
                  f"{[(r.get('star_id') or r.get('author_id'), r[col]) for r in bad]}")
        report.setdefault("event_counts", {})[field] = len(rows)

    old_counts = {"econ": len(econ_lines) - 1,
                  "chemistry": len([ln for ln in (rv / 'events_chemistry_fnfix.csv').read_bytes().decode('utf-8').split('\n') if ln]) - 1,
                  "math_stats": len([ln for ln in (rv / 'events_math_stats_fnfix.csv').read_bytes().decode('utf-8').split('\n') if ln]) - 1}
    diff = {"econ": {"out": [f"{A5044432173_ID} — D-A gate_age fail, aage=0"], "in": []},
            "chemistry": {"out": [], "in": [f"A5027778630 (2002)"]
                          + ([f"A5091826237 (2001) — machine pass"]
                             if new_pass["A5091826237"] else [])
                          + [f"{A5062352558_ID} (2003) — D-B window"]},
            "math_stats": {"out": [], "in": ["A5017222669 (2002)",
                                             "A5090916445 (2002)"]}}
    if not new_pass["A5091826237"]:
        diff["chemistry"]["not_in"] = [f"A5091826237 — machine restake below the line: "
                                       f"{cal_lines['A5091826237']}"]
    report["old_counts"], report["diff"] = old_counts, diff
    print("\n================ OLD -> NEW EVENT DIFF (cal2026-08-28) ================")
    for f in ("econ", "chemistry", "math_stats"):
        print(f"  {f:10s} {old_counts[f]} -> {report['event_counts'][f]}")
        for d, names in diff[f].items():
            for n in names:
                print(f"      {d:6s} {n}")
    print("=======================================================================\n")

    if STOPS:
        print(f"[run_caliber] {len(STOPS)} STOP condition(s) — NOTHING frozen. Report and stop.")
        (out_root / "run_report_FAILED.json").write_text(
            json.dumps({**report, "stops": STOPS}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    # ---- phase F: freeze into data/cal2026-08-28/ -----------------------------------------------
    cand_cols = list(frozen_cands[0].keys())
    all_cand_rows = frozen_cands + new_rows
    _write_dict_csv(CAL_DIR / "candidates_2026-08-28.csv", all_cand_rows, cand_cols)
    # NOTE the frozen gold CSVs are \r\n-terminated (csv.writer default); the raw data lines below
    # were split on "\n" and still carry their "\r", so joining with "\n" keeps every line byte-
    # faithful — the header gets an explicit "\r\n" to match.
    hdr = ",".join(restake_equiv.RESTAKE_HEADER) + "\r\n"
    restake_out = [frozen_restake_lines[r["author_id"]] for r in frozen_restake] \
        + [cal_lines[a] for a in NEW_IDS]
    (CAL_DIR / "restake_2026-08-28.csv").write_text(
        hdr + "\n".join(restake_out) + "\n", encoding="utf-8")
    _write_dict_csv(CAL_DIR / "verdicts_2026-08-28.csv", verdict_rows, list(verdict_rows[0].keys()))
    (CAL_DIR / "restake_ported72_newcands_2026-08-28.csv").write_text(
        hdr + "\n".join(ported_lines[a] for a in NEW_IDS + [A5062352558_ID]) + "\n", encoding="utf-8")
    (CAL_DIR / "restake_equiv_proof_2026-08-28.csv").write_text(
        hdr + "\n".join(proof_lines[a] for a in PROOF_IDS) + "\n", encoding="utf-8")
    for key, name in (("econ", "events_econ_cal.csv"), ("chemistry", "events_chemistry_cal.csv"),
                      ("math_stats", "events_math_stats_cal.csv")):
        (CAL_DIR / name).write_text(events[key], encoding="utf-8")
    (CAL_DIR / "run_report_2026-08-28.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = "".join(f"{_sha(f)}  data/cal2026-08-28/{f.name}\n"
                       for f in sorted(CAL_DIR.iterdir())
                       if f.is_file() and f.name != "MANIFEST.sha256")
    (CAL_DIR / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    print(f"[run_caliber] frozen {manifest.count(chr(10))} files + MANIFEST into {CAL_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
