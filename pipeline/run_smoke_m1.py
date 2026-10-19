"""U1-M1 full-run smoke driver (Monash+UNSW) — assembles registry + econ_dept_ids + reproducibility vouchers + disk preflight → run_full.

launch-ready cross-unit driver:
  - default dry_run (safe): builds registry/econ_dept_ids/vouchers + counts shards + prints the plan; never reads the full data, never writes to disk.
  - --execute: real run (~18h / reads 696GB / writes bucketed narrow tables); needs a manual go-ahead + disk preflight pass + real reproducibility-voucher values.
Rule-neutral: econ_dept_ids come from table A (Monash+UNSW, fold canonical); registry = all education
  (incl. foreign; Yves Zenou's Stockholm folds back too); the reproducibility vouchers are all computed
  deterministically (never None/placeholders polluting run_manifest).

★Before --execute: out_root must not contain a stale `<table>/data.parquet` (part-2 reader: data.parquet
  takes priority over bucket=*), otherwise the old single file shadows the new buckets. First clear the stale
  data.parquet (data_SAMPLE does not block, the reader never reads it), or use a fresh root.

Run:
  dry-run:  python run_smoke_m1.py --out-root "<SAR_DERIVED_ROOT>/u1_edges"
  real run: ... --execute --n-workers 4   (detached from the session, in the background; after it finishes verify the Yves Zenou gold standard)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

_HERE = pathlib.Path(__file__).resolve().parent
for _u in ("u0_foundation", "u1_fetch", "u0p5_dept_roster"):
    _src = _HERE / "units" / _u / "src"
    if str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from common._redlines import require                              # noqa: E402
from identity.constants import build_registry_by_id              # noqa: E402
from m1_ingest.registry_build import load_education_registry      # noqa: E402
from m1_ingest.repro_creds import compute_repro_creds            # noqa: E402
from m1_ingest.run_m1_full import run_full, DEFAULT_BUCKET_ROW_CAP  # noqa: E402
from roster.table_a import (                                       # noqa: E402
    build_table_a_rows, build_table_a_rows_all, build_econ_dept_ids)

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import sys as _sar_sys
_sar_repo = pathlib.Path(__file__).resolve().parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import snapshot_root as _sar_snapshot_root  # noqa: E402
DEFAULT_SNAPSHOT_ROOT = str(_sar_snapshot_root())
REDLINES_PATH = _HERE / "contracts" / "redlines.yaml"
# code_version pins these key pipeline sources (change any one → code_version changes → run_manifest can trace it).
_CODE_SRC = [
    __file__,
    str(_HERE / "units/u1_fetch/src/m1_ingest/registry_build.py"),
    str(_HERE / "units/u1_fetch/src/m1_ingest/run_m1_full.py"),
    str(_HERE / "units/u1_fetch/src/m1_ingest/stream_build.py"),
    str(_HERE / "units/u1_fetch/src/m1_ingest/run_m1.py"),
]
# Conservative smoke reservation (the Monash+UNSW kept-set is small, but leave ample margin before launching; the full 11-school run is budgeted separately).
_MIN_FREE_BYTES = 50 * 1024**3


# Registry version switch — frozen two-school default (can be rolled back) vs the 11-school registry v3.
#   The seed is folded from the table A rows in the code (EC2 only rsyncs the code and carries no SSD roster parquet), so what is selected is a
#   builder function, not a read of the registry_v3 parquet (the parquet = frozen artifact / provenance; its on-disk sha equals
#   build_table_a_rows_all() — guarded by roster/registry_v3.py TABLE_A_SHA).
_TABLE_A_BUILDERS = {"two": build_table_a_rows, "v3": build_table_a_rows_all}


def select_table_a_rows(registry_version: str = "two") -> list:
    """Pick table A rows by registry version: "two" (default, frozen two schools Monash+UNSW) / "v3" (11 schools).

    Unknown version → fail-loud (never silently degrade). No change to the identification rules — it only selects an existing row set and leaves row contents unchanged.
    """
    try:
        builder = _TABLE_A_BUILDERS[registry_version]
    except KeyError:
        raise ValueError(
            f"unknown registry_version: {registry_version!r} (supported: {sorted(_TABLE_A_BUILDERS)})")
    return builder()


def build_inputs(snapshot_root, *, registry_version: str = "two"):
    """registry (all education, incl. foreign) + econ_dept_ids (table A folded to canonical).

    registry_version="two" (default) = the two frozen schools Monash+UNSW (frozen pipeline, zero regression);
    registry_version="v3"        = the 11-school registry v3 (with the department-boundary rules for 4 edge types).
    """
    registry = load_education_registry(snapshot_root)
    registry_by_id = build_registry_by_id(registry)
    econ_dept_ids = build_econ_dept_ids(
        select_table_a_rows(registry_version), registry_by_id)
    return registry, econ_dept_ids


def disk_preflight(out_root) -> dict:
    """Simple disk gate (smoke level): free space on the output volume > reservation → pass; otherwise HALT (with --execute)."""
    probe = pathlib.Path(out_root)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(str(probe))
    return {"free_gb": round(usage.free / 1024**3, 1),
            "min_free_gb": _MIN_FREE_BYTES // 1024**3,
            "ok": usage.free > _MIN_FREE_BYTES}


def run_smoke(snapshot_root, out_root, *, execute=False, n_workers=4,
              bucket_row_cap=DEFAULT_BUCKET_ROW_CAP, max_shards=None,
              reconcile=False, scan_workers=1, ckpt_every=100,
              byline_hits_path=None, registry_version="two", reduce_workers=0,
              roster_seed_paths=None) -> dict:
    """Assemble inputs + vouchers + preflight → run_full. execute=False (default) only emits the plan; no full read, no disk write.
    If max_shards is set, only the first N shards run (subset smoke test of the launch path; not given = full).
    reconcile=True → turn on the four-number reconciliation, tolerance read from the red line reconcile.diff_tolerance (C9: 0; stop on a difference of 1 record).
    byline_hits_path: wiring (b) — path of byline_dept_hits.parquet; if given, the author_id of hit rows with institution=None are merged into the pass-A seeds (leavers with an empty institution; 83 people confirmed at the two schools).
    roster_seed_paths: U1 seed-supplement arm (E5) — list of roster parquet paths; if given, roster author_ids are injected directly into the pass-A seeds (extracted / unioned with the byline arm at the library layer run_full; fixes people missed in collection). Not given = None, existing runs unchanged. A missing path fails loudly."""
    # fail-loud: roster paths must exist first (never enter an 18h full run with a defect; the library layer reads lazily, so the launcher catches it).
    if roster_seed_paths:
        _missing = [str(p) for p in roster_seed_paths if not pathlib.Path(p).is_file()]
        if _missing:
            raise RuntimeError(
                f"roster seed paths do not exist ({len(_missing)}): {_missing} → HALT (stopped before launch)")
    # Scale-up discipline: a real full run must turn on the four-number reconciliation + an external manifest anchor (A2/A3).
    #   This driver is the launch command of the full run — the discipline assertion lives in the launcher; subset smoke runs (max_shards) are exempt.
    if execute and max_shards is None and not reconcile:
        raise RuntimeError(
            "scale-up discipline (#8): a real full run (execute without max_shards) needs --reconcile "
            "(four-number reconciliation + external manifest anchor, A2/A3); for a subset smoke run set --max-shards."
        )
    disk = disk_preflight(out_root)
    if execute and not disk["ok"]:
        raise RuntimeError(
            f"disk preflight failed: free {disk['free_gb']}GB < reserved {disk['min_free_gb']}GB → HALT (never start a run in a bad state)"
        )

    registry, econ_dept_ids = build_inputs(
        snapshot_root, registry_version=registry_version)
    # wiring (b): the extractor takes only the author_id of hit rows with an empty institution (minimal set).
    extra_seed_authors = None
    if byline_hits_path is not None:
        from m1_ingest.run_m1_full import byline_empty_inst_seed_authors
        extra_seed_authors = byline_empty_inst_seed_authors(byline_hits_path)
    creds = compute_repro_creds(
        snapshot_manifest_path=pathlib.Path(snapshot_root) / "manifest.json",
        redlines_path=REDLINES_PATH,
        code_src_paths=_CODE_SRC,
        econ_dept_ids=econ_dept_ids,
        n_workers=n_workers,
        bucket_row_cap=bucket_row_cap,
    )
    # Resumable pass-A checkpoint lands in out_root/_pass_a_ckpt (after a crash, rerun without clearing out_root → it continues from the checkpoint).
    reconcile_kw = {}
    if reconcile:
        # C9 (tolerance 0): the value is read from the red lines only; no numeric knob is exposed on the CLI (so the rule cannot be bypassed).
        # A2 anchor: the operator (= this driver) reads the snapshot's top-level manifest.json
        #   and passes it in as the external truth anchor (by design the assembly layer does not load it automatically; the operator provides it); if the file is missing → fail loudly.
        from m0_snapshot.manifest_reconcile import parse_top_manifest
        _mf_path = pathlib.Path(snapshot_root) / "manifest.json"
        reconcile_kw = dict(
            reconcile=True,
            reconcile_diff_tolerance=require("reconcile", "diff_tolerance"),
            reconcile_manifest=parse_top_manifest(_mf_path.read_bytes()),
        )
    result = run_full(
        snapshot_root, out_root,
        registry=registry, econ_dept_ids=econ_dept_ids,
        n_workers=n_workers, bucket_row_cap=bucket_row_cap,
        execute=execute, max_shards=max_shards,
        extra_seed_authors=extra_seed_authors,   # wiring (b); None = no hits provided (the plan echoes 0)
        roster_seed_paths=roster_seed_paths,     # roster seed arm; None = no injection (the plan echoes count=0)
        run_compact_dedup=True,   # scale-up discipline: the driver layer explicitly confirms the A3 dedup guard is on (there is no switch to turn it off)
        pass_a_ckpt_dir=str(pathlib.Path(out_root) / "_pass_a_ckpt"),
        scan_workers=scan_workers,
        pass_a_checkpoint_every_n=ckpt_every,
        reduce_workers=reduce_workers,   # the reduce phase runs in parallel per bucket (0 = auto min(cpu, bucket count); cuts the ~45% tail bottleneck)
        **reconcile_kw,
        **creds,
    )
    # launch-ready self-check: dry-run also reports input assembly + preflight + voucher readiness.
    result["registry_version"] = registry_version   # provenance: which department boundary (two/v3) this run's seed uses
    result["registry_education_count"] = len(registry)
    result["econ_dept_ids"] = sorted(econ_dept_ids)
    result["disk_preflight"] = disk
    result["repro_creds_ready"] = sorted(creds)  # return only the keys, do not print sha values (clean)
    return result


def _parser():
    p = argparse.ArgumentParser(
        description="U1-M1 full smoke driver (Monash+UNSW; dry-run by default; --execute does the real run and needs an explicit go-ahead)")
    p.add_argument("--snapshot-root", default=DEFAULT_SNAPSHOT_ROOT)
    p.add_argument("--out-root", required=True, help="root for the narrow-table output (SSD derived/u1_edges)")
    p.add_argument("--n-workers", type=int, default=4)
    p.add_argument("--bucket-row-cap", type=int, default=DEFAULT_BUCKET_ROW_CAP)
    p.add_argument("--execute", action="store_true", help="real run (~18h/696GB); omitted = dry-run")
    p.add_argument("--max-shards", type=int, default=None,
                   help="run only the first N shards (smoke-test the launch path on a subset; omitted = all)")
    p.add_argument("--reconcile", action="store_true",
                   help="enable the four-number reconciliation (tolerance = red line reconcile.diff_tolerance=0, C9)")
    p.add_argument("--scan-workers", type=int, default=1,
                   help="number of parallel workers for the pass-A/C scan (1 = old behaviour; on cloud use vCPU-2)")
    p.add_argument("--reduce-workers", type=int, default=0,
                   help="number of parallel workers for the reduce stage, by bucket (0 = auto min(cpu, buckets); 1 = old serial; "
                        "removes the biggest bottleneck, the final merge of 256 buckets × 5 tables - nearly half of a tuned full run; byte-for-byte equivalent to serial)")
    p.add_argument("--ckpt-every", type=int, default=100,
                   help="pass-A checkpoint every N shards (when parallel = shards per round; on cloud 400-600 spreads out the checkpoint cost)")
    p.add_argument("--byline-hits", default=None,
                   help="wiring (b): byline_dept_hits.parquet path; "
                        "hit author_ids with an empty institution are merged into the pass-A seeds (leavers with an empty institution)")
    p.add_argument("--registry-version", choices=("two", "v3"), default="two",
                   help="department-boundary seed version: two (default, frozen Monash+UNSW) / "
                        "v3 (11-school registry v3)")
    p.add_argument("--roster-seed", nargs="+", default=None, metavar="PARQUET",
                   help="roster parquet path (repeatable); "
                        "author_ids are injected directly into the pass-A seeds, unioned with the byline arm (merged in the library-level run_full); "
                        "omitted = no injection (existing runs unchanged)")
    return p


if __name__ == "__main__":
    _a = _parser().parse_args()
    _out = run_smoke(_a.snapshot_root, _a.out_root, execute=_a.execute,
                     n_workers=_a.n_workers, bucket_row_cap=_a.bucket_row_cap,
                     max_shards=_a.max_shards, reconcile=_a.reconcile,
                     scan_workers=_a.scan_workers, ckpt_every=_a.ckpt_every,
                     byline_hits_path=_a.byline_hits,
                     registry_version=_a.registry_version,
                     reduce_workers=_a.reduce_workers,
                     roster_seed_paths=_a.roster_seed)
    print(json.dumps(_out, ensure_ascii=False, indent=2))
