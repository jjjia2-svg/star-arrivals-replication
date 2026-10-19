"""run_gates: M7c control-flow orchestrator. Chains the five gates, safest tier first.

Verdict order: HALT > HUMAN_REVIEW > WARN > PASS.
  - HALT = a named exception propagates upward (the exit code is mapped from the exception type at the CLI layer, B6-EXITCODE discipline);
    before raising, the reports collected so far are written atomically to disk (they do not vanish silently).
  - C2: frame fwci_frac NA rate > 20% -> global HUMAN_REVIEW (not overridden by PASS/WARN).
Provenance has two lines: (1) the loading layer (io_real) has already verified each upstream artifact header (first line);
(2) this gate re-verifies the header of the U6-produced frozen frame against this run's config 4-tuple (second line, guarding against edits after writing)
+ consistency of the double-anchor shared keys (u4 / u5_ship).
"""
from __future__ import annotations

import json
import pathlib

from common.atomic_io import atomic_write_bytes
from common.manifest import PROVENANCE_KEYS, verify_provenance

from . import attrition_gate as ag
from . import frame_gate as fg
from . import golden_gate as gg
from . import provenance_gate as pg
from . import reconcile_gate as rg
from m7b_assemble import incumbent_roster as ir

_ORDER = ("HALT", "HUMAN_REVIEW", "WARN", "PASS")


def combine_verdicts(verdicts) -> str:
    vs = set(verdicts)
    for v in _ORDER:
        if v in vs:
            return v
    return "PASS"


def _write_report(reports_dir: pathlib.Path, name: str, doc: dict) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(reports_dir / name,
                       json.dumps(doc, ensure_ascii=False, sort_keys=True,
                                  indent=1, default=str).encode("utf-8"))


def run_gates(out_root, inputs, *, config: dict) -> dict:
    out_root = pathlib.Path(out_root)
    reports_dir = out_root / "_reports"
    gates: dict = {}
    verdicts: list = []

    def _finalize(summary_verdict: str) -> dict:
        summary = {"verdict": summary_verdict,
                   "gates": {k: v.get("verdict") for k, v in gates.items()
                             if isinstance(v, dict)}}
        _write_report(reports_dir, "u6_gates_summary.json", summary)
        return summary

    try:
        # --- ① G-frame -------------------------------------------------------
        frame_res = fg.run_frame_gate(out_root)
        gates["frame"] = frame_res
        _write_report(reports_dir, "u6_gate_frame.json", frame_res)
        verdicts.append(frame_res["verdict"])

        # --- (2) G-prov (double anchor + second-line check of the U6-produced header) --------------------------------
        prov = inputs.upstream_provenance
        pg.assert_cross_anchor_consistent(prov["u4"], prov["u5"])
        headers = {"star_set": prov["u4"], "events": prov["u4"],
                   "dose_p01": prov["u5"], "dose_p05": prov["u5"],
                   "output": prov["u5"]}
        prov_res = pg.run_provenance_gate(headers, dict(headers))
        u6_header = json.loads((out_root / "frame" / "_frozen"
                                / "manifest_header.json").read_text())
        verify_provenance(u6_header,
                          {k: str(config[k]) for k in PROVENANCE_KEYS})
        gates["provenance"] = prov_res
        _write_report(reports_dir, "u6_gate_provenance.json", prov_res)
        verdicts.append(prov_res["verdict"])

        # --- ③ G-golden ------------------------------------------------------
        golden_res = gg.run_golden_gate(
            star_set=inputs.star_set, events=inputs.events,
            person_map=inputs.person_map, panel=inputs.panel)
        gates["golden"] = golden_res
        _write_report(reports_dir, "u6_gate_golden.json", golden_res)
        verdicts.append(golden_res["verdict"])

        # --- (4) attrition diagnostic (record and surface, no HALT) -------------
        members, _ = ir.fold_roster_to_persons(inputs.roster, inputs.person_map)
        bridge = ir.bridge_dept_to_inst(inputs.registry)
        idx = ir.build_in_dept_index(members, inputs.panel, bridge)
        events_by_id = inputs.events_by_id()
        last_pub: dict = {}
        for p in inputs.panel:
            if (p.get("n_works_year") or 0) > 0:
                cur = last_pub.get(p["person_id"])
                last_pub[p["person_id"]] = max(cur, p["year"]) \
                    if cur is not None else p["year"]
        pairs = []
        seen = set()
        for lev in ("p01", "p05"):
            for d in inputs.dose.get(lev, ()):
                key = (d["incumbent_person_id"], d["event_id"])
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({
                    "incumbent_person_id": d["incumbent_person_id"],
                    "event_id": d["event_id"],
                    "arrival_year": events_by_id[d["event_id"]]["arrival_year"],
                })
        from common._redlines import RED

        att_res = ag.run_attrition_diag(
            pairs, membership_end=idx.membership_end,
            last_pub_year=last_pub.get,
            window_years=int(RED["cohort"]["event_window_years"]),
            control_pairs=())
        gates["attrition"] = att_res
        _write_report(reports_dir, "u6_gate_attrition.json", att_res)
        verdicts.append(att_res["verdict"])

        # --- ⑤ G-reconcile ---------------------------------------------------
        tally_paths = sorted((out_root / "_ledger").glob("*/tally.json"))
        rec_res = rg.run_reconcile_gate(tally_paths)
        gates["reconcile"] = rec_res
        _write_report(reports_dir, "u6_gate_reconcile.json", rec_res)
        verdicts.append(rec_res["verdict"])

        # --- C2: NA>20% -> HUMAN_REVIEW propagation (read from m7b output_diag) -----------
        diag = json.loads((reports_dir / "output_diag.json").read_text())
        for lev in ("p01", "p05"):
            if diag.get(lev, {}).get("na_robustness_required"):
                verdicts.append("HUMAN_REVIEW")
    except Exception:
        _finalize("HALT")
        raise

    summary = _finalize(combine_verdicts(verdicts))
    result = {**summary, **gates}
    for lev in ("p01", "p05"):
        if lev in gates.get("frame", {}):
            result[lev] = gates["frame"][lev]
    return result
