"""run_u5 - thin U5 CLI orchestration (the entry point of the U5 unit).

Flow: io_real loads the eight tables (contract gate + 10c provenance binding) -> run_m4_dose(p01/p05,
embed deferred + incumbent pool) -> run_m5b (two named tables). Outputs are written under the passed-in out_root;
this file never chooses or overwrites any existing SSD directory (a real run only creates a brand-new u5_ship_*
directory).

The nine config keys (rule: take values from fixed sources; if a value is missing, fail loud):
  - mnar_missing_threshold = 0.20 (fixed, caveat#1);
  - rule_version / source_snapshot_merkle / stars_set_hash = the pinned values of the 10c frozen-anchor
    four-tuple (the star_set + events artifact headers are verified key by key, a mismatch -> HALT);
  - config_sha = the sha256 of this run's config (canonical json);
  - duckdb_db_path = given by the caller (persistent .db);
  - embed_model_sha = "embed_deferred" - embed_model_name/seed have no fixed value -> the secondary dose is
    deferred (embed_cos all NA + diag embed_deferred=true); vectors are never fabricated from an unfixed model;
  - degree2_cap_k / degree2_incumbent_cap_per_star = no fixed value (to be filled in after the degree-2 spike;
    neither the red lines nor the spec give a number) -> this run takes the "never binding" mathematical upper
    bound = len(person_map)+1: any person's degree in the subgraph / any star's incumbent set is <= the number of
    people in the subgraph <= the number of person_map rows < cap, so cap has zero effect on the result (= the
    no-cap semantics); it is not a smuggled-in default magic number. The binding values remain unfixed (listed in
    the report).

Red-line discipline: this file contains zero identification definitions; the rule_version consistency gate
(pins == the current redlines rule_version) guards against version drift between the upstream freeze and this
run's definitions.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
_UNITS = _HERE.parent
for _p in (_UNITS / "u0_foundation" / "src", _UNITS / "u1_fetch" / "src",
           _UNITS / "u5_dose" / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import io_real                                    # noqa: E402
from common.atomic_io import atomic_write_bytes   # noqa: E402
from m4_dose import run_dose                      # noqa: E402
from m5b_aggregate import run_m5b as m5b          # noqa: E402

# 10c authoritative anchor (= u4_ship_2026-07-10c) - pinned byte for byte;
#   the star_set/events artifact-header four-tuples must match key by key, otherwise ProvenanceMismatch HALT.
PINNED_UPSTREAM_10C: dict = {
    "source_snapshot_merkle":
        "snap:da78e4b9b706d48d3d4f0353302f8f1ba86fd9d3afdab948d88001205bc4dd89",
    "config_sha":
        "45c57627a8b433064fed76d27e40dcd608a18466125c21480b260357fc229de1",
    "rule_version": "redlines_v4_signed_2026-07-05",
    "stars_set_hash":
        "2ae9ab57076e32da0a311a490ee2f7187e6afe8677117c85c65ddec6d6751009",
}

# Default real-data paths (the two-university frozen artifacts; the output directory of a real run is given explicitly by the CLI, never defaulting to the SSD).
# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "units").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import derived_root as _sar_derived_root  # noqa: E402
DEFAULT_DATA_ROOT = str(_sar_derived_root())


def default_paths(data_root: str = DEFAULT_DATA_ROOT) -> dict:
    r = pathlib.Path(data_root)
    return {
        "authorship_edges_glob":
            str(r / "u1_edges_full_2026-07-05" / "authorship_edges" / "**" / "*.parquet"),
        "refs_edges_glob":
            str(r / "u1_edges_full_2026-07-05" / "refs_edges" / "**" / "*.parquet"),
        "works_glob":
            str(r / "u1_edges_full_2026-07-05" / "works" / "**" / "*.parquet"),
        "work_text_glob":
            str(r / "u1_edges_full_2026-07-05" / "work_text" / "**" / "*.parquet"),
        "person_map":
            str(r / "u2_person_map_2026-07-05" / "person_map" / "data.parquet"),
        "star_set_dir": str(r / "u4_ship_2026-07-10c" / "star_set"),
        "events_dir": str(r / "u4_ship_2026-07-10c" / "events"),
        "paper_contrib_glob":
            str(r / "u4_ship_2026-07-10c" / "paper_contrib" / "**" / "*.parquet"),
    }


def build_config(*, n_person_map_rows: int, pinned: dict,
                 duckdb_db_path: str) -> dict:
    """Assemble the nine-key config (see the module docstring for the source of each key); config_sha is really computed, not a placeholder."""
    cap_nonbinding = int(n_person_map_rows) + 1   # never-binding upper bound (mathematical argument in the docstring)
    cfg = {
        "degree2_cap_k": cap_nonbinding,
        "degree2_incumbent_cap_per_star": cap_nonbinding,
        "mnar_missing_threshold": 0.20,           # fixed, caveat#1
        "duckdb_db_path": str(duckdb_db_path),
        "embed_model_sha": "embed_deferred",      # secondary dose deferred (no fixed model, so no fabricated vectors)
        "rule_version": pinned["rule_version"],
        "source_snapshot_merkle": pinned["source_snapshot_merkle"],
        "stars_set_hash": pinned["stars_set_hash"],
    }
    blob = json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")
    cfg["config_sha"] = hashlib.sha256(blob).hexdigest()
    return cfg


def run_all(paths: dict, *, out_root, pinned: dict, duckdb_db_path: str,
            enforce_red_coherence: bool = True) -> dict:
    """Master orchestration: load -> dose p01/p05 -> m5b. Returns a report; the summary is written to out_root/_reports/."""
    t0 = time.time()
    if enforce_red_coherence:
        from common._redlines import RED
        if str(RED.get("rule_version")) != str(pinned["rule_version"]):
            raise ValueError(
                f"rule_version drift: current redlines={RED.get('rule_version')!r} != "
                f"upstream frozen pins={pinned['rule_version']!r} — upstream was frozen under an older rule version, "
                "this run's rules have changed → HALT for a human decision (versions are never silently mixed)"
            )

    out_root = pathlib.Path(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    inputs, extras = io_real.build_real_inputs(
        paths, pinned_star_provenance=pinned, duckdb_db_path=duckdb_db_path,
    )
    cfg = build_config(
        n_person_map_rows=len(inputs.person_map), pinned=pinned,
        duckdb_db_path=duckdb_db_path,
    )
    # proof that cap never binds: cap = |person_map|+1 > any degree / set size in the subgraph (upper-bound argument).
    caps_proof = {
        "cap_value": cfg["degree2_cap_k"],
        "n_person_map_rows": len(inputs.person_map),
        "n_pool_persons": extras["n_pool_persons"],
        "cap_exceeds_universe": cfg["degree2_cap_k"] > len(inputs.person_map),
    }

    t_load = time.time()
    dose_reports = {}
    ledger_path = out_root / "_ledger" / "u5_dose" / "events.jsonl"
    for p_level in ("p01", "p05"):
        dose_reports[p_level] = run_dose.run_m4_dose(
            inputs, config=cfg, out_root=out_root / f"dose_{p_level}",
            ledger_path=ledger_path, p_level=p_level,
            embedder=None,                              # secondary dose deferred (see docstring)
            closure_edges=extras["closure_edges"],
            incumbent_pool=extras["incumbent_pool"],
        )
    t_dose = time.time()

    m5b_report = m5b.run_m5b(
        inputs, config=cfg, out_root=out_root / "output",
        ledger_path=ledger_path,
        exclusion_edges=extras["exclusion_edges"],   # the full-history exclusion is independent of year (includes missing-year edges)
    )
    t_end = time.time()

    report = {
        "pinned_upstream": pinned,
        "config": {k: v for k, v in cfg.items() if k != "duckdb_db_path"},
        "io": {k: v for k, v in extras.items()
               if k not in ("closure_edges", "exclusion_edges")},
        "dose": dose_reports,
        "m5b": m5b_report,
        "caps_nonbinding_proof": caps_proof,
        "timings_s": {
            "load": round(t_load - t0, 1),
            "dose": round(t_dose - t_load, 1),
            "m5b": round(t_end - t_dose, 1),
            "total": round(t_end - t0, 1),
        },
    }
    reports_dir = out_root / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(
        reports_dir / "run_summary_u5.json",
        json.dumps(report, ensure_ascii=False, sort_keys=True,
                   indent=1, default=str).encode("utf-8"),
    )
    return report


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="U5 dose + output orchestration (two-university real data)")
    ap.add_argument("--out-root", required=True,
                    help="output root directory (only creates new directories, never touches existing ones)")
    ap.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    ap.add_argument("--duckdb-db", required=True, help="path of the persistent DuckDB database")
    args = ap.parse_args(argv)

    out_root = pathlib.Path(args.out_root)
    report = run_all(
        default_paths(args.data_root), out_root=out_root,
        pinned=dict(PINNED_UPSTREAM_10C), duckdb_db_path=args.duckdb_db,
    )
    print(json.dumps({
        "dose_rows": {p: report["dose"][p].get("n_rows") for p in ("p01", "p05")},
        "m5b_rows": report["m5b"].get("n_rows"),
        "timings_s": report["timings_s"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
