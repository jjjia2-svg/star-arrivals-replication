"""run_power: m7d block entry point: load_frame (x2) -> mde (two percentiles) ->
g_treated -> reporting -> seal run_manifest.

HIGH-3: read only, compute only, seal only. An observation out of range is recorded in the tolerance bucket and does not HALT (HALT belongs to
M7c), and nothing is re-joined (HIGH-1).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import pathlib
import sys

from common._redlines import RED

from . import g_treated as gt
from . import load_frame as lf
from . import mde
from . import reporting_fields as rf
from . import run_manifest as rm

_MDE_TXT = {"p01": "mde_1pct.txt", "p05": "mde_5pct.txt"}


def _stage_shas() -> dict:
    import m7b_assemble.assemble as _a
    import m7c_gates.run_gates as _g

    out = {}
    for name, mod in (("m7b_assemble", _a), ("m7c_gates", _g),
                      ("m7d_power", sys.modules[__name__])):
        src = inspect.getsource(mod)
        out[name] = hashlib.sha256(src.encode("utf-8")).hexdigest()
    return out


def _env_lock_sha() -> str:
    import pyarrow

    blob = json.dumps({"python": sys.version.split()[0],
                       "pyarrow": pyarrow.__version__},
                      sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def run_power(out_root, inputs, *, config: dict, gates_result: dict) -> dict:
    out_root = pathlib.Path(out_root)
    reports_dir = out_root / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    dept_of_event = {e["event_id"]: e["dept_id"] for e in inputs.events}
    frames = {p: lf.load_frame(out_root, p) for p in ("p01", "p05")}

    mde_reports: dict = {}
    for p_level, rows in frames.items():
        label = "1pct" if p_level == "p01" else "5pct"
        rep, txt = mde.compute_mde_report(rows, dept_of_event, p_label=label)
        (reports_dir / _MDE_TXT[p_level]).write_text(txt, encoding="utf-8")
        mde_reports[p_level] = rep

    g_counts = gt.count_g_treated(inputs.events, inputs.star_set)

    golden = gates_result.get("golden", {})
    diag = json.loads((reports_dir / "output_diag.json").read_text())
    att = gates_result.get("attrition", {})
    boundary_flips = sum(
        1 for lev in ("p01", "p05")
        for d in inputs.dose.get(lev, ()) if d.get("boundary_sensitive"))

    frame_stats = {p: {"n_rows": len(frames[p]),
                       "pk_sha256": gates_result[p]["pk_sha256"]}
                   for p in ("p01", "p05")}
    reporting = rf.collect_reporting(
        frame_stats={p: frame_stats[p]["n_rows"] for p in frame_stats},
        source_snapshot_merkle=str(config["source_snapshot_merkle"]),
        rule_version=str(config["rule_version"]),
        snapshot_api_note=config.get("snapshot_api_note"))

    deterministic = {
        "source_snapshot_merkle": str(config["source_snapshot_merkle"]),
        "config_sha": str(config["config_sha"]),
        "rule_version": str(config["rule_version"]),
        "stars_set_hash": str(config["stars_set_hash"]),
        "env_lock_sha": _env_lock_sha(),
        "stage_shas": _stage_shas(),
        "analysis_frame_p01_pk_sha256": frame_stats["p01"]["pk_sha256"],
        "analysis_frame_p05_pk_sha256": frame_stats["p05"]["pk_sha256"],
        "G_treated_1pct": g_counts["p01"],
        "G_treated_5pct": g_counts["p05"],
        "golden_structural_pass": bool(golden.get("structural_pass")),
        "provenance_quad": inputs.upstream_provenance,
    }
    tolerance = {
        "mde_1pct": f"see _reports/{_MDE_TXT['p01']}",
        "mde_5pct": f"see _reports/{_MDE_TXT['p05']}",
        "golden_works_count_observed": golden.get("works_count_observed"),
        "golden_arrival_year_observed": golden.get("arrival_year_observed"),
        "golden_observed_in_range": golden.get("observed_in_range"),
        "golden_anchored_release": golden.get("anchored_release"),
        "golden_topics_version": golden.get("topics_version"),
        "boundary_sensitive_flip_count": boundary_flips,
        "na_rate_fwci_frac": {p: diag[p]["na_rate_fwci_frac"]
                              for p in ("p01", "p05")},
        "lee_bounds_required": att.get("lee_bounds_required"),
    }
    expected_source_types = {
        "analysis_frame_p01": "derived", "analysis_frame_p05": "derived",
        "star_set": "derived", "events": "derived", "dose_p01": "derived",
        "dose_p05": "derived", "output": "derived",
        "source_snapshot_merkle": "a-priori",
    }
    rm.seal_run_manifest(out_root / "run_manifest.lock",
                         deterministic=deterministic, tolerance=tolerance,
                         reporting=reporting,
                         expected_source_types=expected_source_types)
    return {
        "G_treated": g_counts,
        "mde": {p: {"n_clusters": mde_reports[p]["n_clusters"],
                    "icc": mde_reports[p]["icc_estimate"],
                    "strata_sizes": mde_reports[p]["strata_sizes"],
                    "contrasts": {k: v.get("mde")
                                  for k, v in mde_reports[p]["contrasts"]
                                  .items()}}
                for p in ("p01", "p05")},
        "sealed": str(out_root / "run_manifest.lock"),
    }
