# -*- coding: utf-8 -*-
"""step3 — U6 assembly (52-event version, frame rules v1.1 with all fixes as is, same part as the 16-event version).

Inputs switched to the 52-event version:
  star_set/events <- u4_star_set_52ev_2026-07-21
  dose/output     <- u5_ship_11school_52ev_2026-07-21
  roster          <- u4_star_set_52ev_2026-07-21/_roster_pool (11 schools, Adelaide gap-filled version,
                    stars already removed from the pool)
Produces: u6_ship_11school_52ev_2026-07-21/.
How to run (original layout): cd multiplex_pipeline && PYTHONHASHSEED=0 python3 <working scripts>/final52_2026-07-21/step3_run_u6.py
"""
import hashlib
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_MP = _HERE.parents[1]
sys.path[:0] = [str(_HERE),
                str(_MP / "units" / "u0_foundation" / "src"),
                str(_MP / "units" / "u1_fetch" / "src"),
                str(_MP / "units" / "u6_assemble" / "src"),
                str(_MP / "units" / "u6_assemble")]
from common80 import (EDGES_SUB, NINE_SCHOOLS, PANEL_SUB, PM_DIR,  # noqa: E402
                      REGISTRY_TABLE_A, SSD, U4_OUT, U5_OUT, U6_OUT)
import io_real  # noqa: E402
import run_u6  # noqa: E402
from common._redlines import RED, REDLINES_YAML  # noqa: E402

FRAME_FIX_VERSION = "v1.1_2026-07-19_review_fixes"
RUN_TAG = "final52ev_2026-07-21_author_task"


def _quad(header_path):
    d = json.loads(pathlib.Path(header_path).read_text("utf-8"))
    return {k: d[k] for k in ("source_snapshot_merkle", "config_sha",
                              "rule_version", "stars_set_hash")}


PINS_U4 = _quad(U4_OUT / "star_set" / "manifest_header.json")
PINS_U5 = _quad(U5_OUT / "output" / "_frozen" / "manifest_header.json")

POOL = U4_OUT / "_roster_pool"
ROSTER_FILES = [str(POOL / f"dept_roster_panel_{s}.parquet")
                for s in list(NINE_SCHOOLS) + ["monash", "unsw"]]

PATHS = {
    "person_map": str(SSD / PM_DIR / "data.parquet"),
    "star_set_dir": str(U4_OUT / "star_set"),
    "events_dir": str(U4_OUT / "events"),
    "dose_p01_dir": str(U5_OUT / "dose_p01"),
    "dose_p05_dir": str(U5_OUT / "dose_p05"),
    "output_dir": str(U5_OUT / "output"),
    "roster_files": ROSTER_FILES,
    "registry": str(REGISTRY_TABLE_A),
    "panel_dir": str(SSD / PANEL_SUB / "panel"),
    "work_first_pub_glob": str(SSD / EDGES_SUB / "work_first_pub" / "**" / "*.parquet"),
    "u5_diag_files": {
        "dose_p01": str(U5_OUT / "dose_p01" / "diag.json"),
        "dose_p05": str(U5_OUT / "dose_p05" / "diag.json"),
        "output": str(U5_OUT / "output" / "output_diag.json"),
    },
}


def main():
    for pins in (PINS_U4, PINS_U5):
        if str(RED.get("rule_version")) != str(pins["rule_version"]):
            raise SystemExit(f"HALT rule_version drift: RED={RED.get('rule_version')!r} "
                             f"!= pins={pins['rule_version']!r}")
    cfg = run_u6.build_config(pins_u4=PINS_U4, pins_u5=PINS_U5,
                              redlines_path=REDLINES_YAML)
    cfg["frame_fix_version"] = FRAME_FIX_VERSION
    cfg["run_tag"] = RUN_TAG
    blob = json.dumps({k: v for k, v in cfg.items() if k != "config_sha"},
                      sort_keys=True, ensure_ascii=False).encode("utf-8")
    cfg["config_sha"] = hashlib.sha256(blob).hexdigest()
    print(f"frame_fix={FRAME_FIX_VERSION} run_tag={RUN_TAG} "
          f"config_sha={cfg['config_sha'][:16]}..")
    try:
        inputs = io_real.build_real_inputs(PATHS, pins_u4=PINS_U4, pins_u5=PINS_U5)
        report = run_u6.run_all(inputs, out_root=U6_OUT, config=cfg, force=True)
    except Exception as exc:  # noqa: BLE001
        code = run_u6.exit_code_for(exc)
        print(f"[U6] HALT {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(code)
    print(json.dumps({
        "frame_rows": report.get("m7b", {}).get("n_rows"),
        "gates_verdict": report.get("gates_verdict"),
        "na_rate_fwci_frac": report.get("m7b", {}).get("na_rate_fwci_frac"),
        "coverage_events": {k: report.get("m7b", {}).get("coverage", {}).get(k)
                            for k in ("events_nominal", "events_in_frame",
                                      "events_dropped_zero_coupling",
                                      "nt_pool_depts", "nt_pool_empty")},
        "G_treated": report.get("power", {}).get("G_treated"),
        "timings_s": report.get("timings_s"),
    }, ensure_ascii=False, indent=1, default=str))
    print("U6_DONE out=", U6_OUT)


if __name__ == "__main__":
    main()
