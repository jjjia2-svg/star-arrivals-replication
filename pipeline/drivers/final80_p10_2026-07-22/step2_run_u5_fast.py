# -*- coding: utf-8 -*-
"""step2 — U5 dose (52-event version, restart with an exact closed-domain reduction, same part as step2b of the 16-event version).

Uses the domain-reduction method shown to work in the 07-20 16-event version (exact reduction of closure_edges; the
byte-for-byte equivalence argument is in the module docstring of final16_2026-07-20/step2b_run_u5_fast.py). The 52-event pool is larger than the
16-event pool (233 star candidates, more schools); running the full closed domain directly would repeat the "2 h with no output" failure, so the
verified reduced version is used directly and the full-domain version is not rerun to "confirm necessity" (already confirmed; no time is spent repeating it).

Produces: u5_ship_11school_52ev_2026-07-21/.
How to run (original layout): cd multiplex_pipeline && PYTHONHASHSEED=0 python3 <working scripts>/final52_2026-07-21/step2_run_u5_fast.py
"""
import json
import pathlib
import sys
import time

_HERE = pathlib.Path(__file__).resolve().parent
_MP = _HERE.parents[1]
sys.path[:0] = [str(_HERE), str(_MP / "units" / "u5_dose"),
                str(_MP / "units" / "u5_dose" / "src"),
                str(_MP / "units" / "u0_foundation" / "src"),
                str(_MP / "units" / "u1_fetch" / "src")]
from common80 import EDGES_SUB, PM_DIR, SSD, U4_OUT, U5_OUT  # noqa: E402
import io_real  # noqa: E402
import run_u5  # noqa: E402
from common.atomic_io import atomic_write_bytes  # noqa: E402
from m4_dose import io_load, run_dose  # noqa: E402
from m5b_aggregate import run_m5b as m5b  # noqa: E402
from m5b_aggregate import star_coauthored_works as scw  # noqa: E402

DB = U5_OUT / "_work" / "u5_subgraph.db"

hdr = json.loads((U4_OUT / "star_set" / "manifest_header.json").read_text("utf-8"))
PINNED = {k: hdr[k] for k in ("source_snapshot_merkle", "config_sha",
                              "rule_version", "stars_set_hash")}

PATHS = {
    "authorship_edges_glob": str(SSD / EDGES_SUB / "authorship_edges" / "**" / "*.parquet"),
    "refs_edges_glob": str(SSD / EDGES_SUB / "refs_edges" / "**" / "*.parquet"),
    "works_glob": str(SSD / EDGES_SUB / "works" / "**" / "*.parquet"),
    "work_text_glob": str(SSD / EDGES_SUB / "work_text" / "**" / "*.parquet"),
    "person_map": str(SSD / PM_DIR / "data.parquet"),
    "star_set_dir": str(U4_OUT / "star_set"),
    "events_dir": str(U4_OUT / "events"),
    "paper_contrib_glob": str(U4_OUT / "paper_contrib" / "**" / "*.parquet"),
}


def reduced_closure_edges(inputs, extras):
    """Closed-domain reduction (edges at the OpenAlex-author level; for the equivalence argument see the module docstring of final16_2026-07-20/step2b)."""
    pm = inputs.person_map
    pid_by_author = {r["author_id"]: r["person_id"] for r in pm}
    pool = set(extras["incumbent_pool"])
    ship_p05, _ = scw.ship_star_person_ids(inputs.star_set, pm, p_level="p05")
    stars = set(ship_p05)

    star_works = {e["work_id"] for e in inputs.authorship_edges
                  if pid_by_author.get(e["author_id"]) in stars}
    mids = {pid_by_author[e["author_id"]] for e in inputs.authorship_edges
            if e["work_id"] in star_works and e["author_id"] in pid_by_author}
    relevant = pool | stars | mids
    kept = [e for e in inputs.authorship_edges
            if pid_by_author.get(e["author_id"]) in relevant]
    note = {
        "n_edges_full_domain": len(inputs.authorship_edges),
        "n_edges_closure_reduced": len(kept),
        "n_star_works": len(star_works), "n_mids": len(mids),
        "n_pool": len(pool), "n_relevant_persons": len(relevant),
        "equivalence": ("cap 恒不触顶 + 两跳 pair 两端点∈保留集 + 共同 work "
                        "全署名边保留 → close_degree2 输出与全域逐字节相同"),
    }
    return kept, note


def main():
    t0 = time.time()
    if U5_OUT.exists() and any(U5_OUT.iterdir()):
        raise SystemExit(f"HALT: {U5_OUT} already exists and is not empty — only a new directory may be created")
    DB.parent.mkdir(parents=True, exist_ok=True)
    print(f"pinned: stars_set_hash={PINNED['stars_set_hash'][:16]}.. "
          f"config_sha={PINNED['config_sha'][:16]}..")

    from common._redlines import RED
    if str(RED.get("rule_version")) != str(PINNED["rule_version"]):
        raise SystemExit("HALT rule_version drift")

    inputs, extras = io_real.build_real_inputs(
        PATHS, pinned_star_provenance=PINNED, duckdb_db_path=str(DB))
    cfg = run_u5.build_config(n_person_map_rows=len(inputs.person_map),
                              pinned=PINNED, duckdb_db_path=str(DB))
    t_load = time.time()
    print(f"io loaded ✓ ({t_load-t0:.0f}s) edges={extras['n_edges_subgraph']} "
          f"pool={extras['n_pool_persons']}")

    closure_edges, closure_note = reduced_closure_edges(inputs, extras)
    print(f"closure-domain reduction ✓ {closure_note['n_edges_full_domain']} → "
          f"{closure_note['n_edges_closure_reduced']} edges "
          f"(mids={closure_note['n_mids']}) ({time.time()-t0:.0f}s)")

    dose_reports = {}
    ledger_path = U5_OUT / "_ledger" / "u5_dose" / "events.jsonl"
    for p_level in ("p01", "p05"):
        dose_reports[p_level] = run_dose.run_m4_dose(
            inputs, config=cfg, out_root=U5_OUT / f"dose_{p_level}",
            ledger_path=ledger_path, p_level=p_level, embedder=None,
            closure_edges=closure_edges,
            incumbent_pool=extras["incumbent_pool"])
        print(f"dose {p_level} ✓ ({time.time()-t0:.0f}s)")
    t_dose = time.time()

    m5b_report = m5b.run_m5b(inputs, config=cfg, out_root=U5_OUT / "output",
                             ledger_path=ledger_path,
                             exclusion_edges=extras["exclusion_edges"])
    t_end = time.time()

    report = {
        "pinned_upstream": PINNED,
        "config": {k: v for k, v in cfg.items() if k != "duckdb_db_path"},
        "io": {k: v for k, v in extras.items()
               if k not in ("closure_edges", "exclusion_edges", "incumbent_pool")},
        "closure_domain_reduction": closure_note,
        "dose": dose_reports,
        "m5b": m5b_report,
        "caps_nonbinding_proof": {
            "cap_value": cfg["degree2_cap_k"],
            "n_person_map_rows": len(inputs.person_map),
            "cap_exceeds_universe": cfg["degree2_cap_k"] > len(inputs.person_map),
        },
        "timings_s": {"load": round(t_load - t0, 1),
                      "dose": round(t_dose - t_load, 1),
                      "m5b": round(t_end - t_dose, 1),
                      "total": round(t_end - t0, 1)},
    }
    reports_dir = U5_OUT / "_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(reports_dir / "run_summary_u5.json",
                       json.dumps(report, ensure_ascii=False, sort_keys=True,
                                  indent=1, default=str).encode("utf-8"))
    print(json.dumps({
        "dose_rows": {p: report["dose"][p].get("n_rows") for p in ("p01", "p05")},
        "m5b_rows": report["m5b"].get("n_rows"),
        "timings_s": report["timings_s"]}, ensure_ascii=False))
    print("U5_DONE out=", U5_OUT)


if __name__ == "__main__":
    main()
