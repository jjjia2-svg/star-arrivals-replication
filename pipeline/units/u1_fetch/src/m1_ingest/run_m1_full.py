"""U1-M1 full-run driver run_m1_full — thin assembly: discover works shards → ShardPathSource → run_m1_streaming.

Why it is separate from run_m1.py (an isolated entry point, zero regression):
  run_m1.py / run_slice_tables are left untouched (46 old tests + 274 all green); this module only chains
  "discover the full works shards → feed run_m1_streaming" and hooks up __main__.
  ★It must live in units/u1_fetch/src/m1_ingest/ (the spawn worker's _worker_sys_path_bridge anchors on the
    units directory; placed further out, the worker's re-import fails).

★Neutral on identification criteria: touches none; argparse has no identification-criterion flags (no --dose/--fwci-window/--diff-tolerance).
★A full large run (hours / reads 696GB / writes hundreds of GB of bucketed parquet) must be switched on explicitly with --execute and its
  preconditions met (a real econ_dept_ids roster / the S2 reduce memory fix done / disk preflight); the default is dry_run, which only counts shards and prints the
  plan, reading no full data and writing nothing. A real run must be given the real reproducibility values explicitly (None → error; placeholders never pollute run_manifest).
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Optional

from m1_ingest.stream_build import run_m1_streaming, ShardPathSource

# Conservative default for the first full run (200k would leave 10 tables x 256 buckets half full and run out of memory → 20k for the full run).
DEFAULT_BUCKET_ROW_CAP = 20_000


def discover_work_shards(snapshot_root) -> list[str]:
    """List all .gz shard paths under snapshot_root/works (recursive + sorted → deterministic across machines and runs)."""
    root = Path(snapshot_root)
    return sorted(glob.glob(str(root / "works" / "**" / "*.gz"), recursive=True))


def byline_empty_inst_seed_authors(hits_path) -> set:
    """Extractor for wiring (b): take the author_id set of the rows in
    byline_dept_hits.parquet with [institution_id=None and a department-name hit].

    Minimal-set discipline: only merge the author_ids of rows whose institution=None hit — not the whole
    table B — which keeps the "byline→seed" coupling to a minimum. Every row of the hits table is already a
    department-name hit (build_dept_hits only writes hit rows), so the only filter left is that institution_id
    is empty. In the two schools, this population is 389 rows / 83 authors.
    """
    import pyarrow.parquet as pq

    table = pq.read_table(str(hits_path), columns=["author_id", "institution_id"])
    aids = table.column("author_id").to_pylist()
    iids = table.column("institution_id").to_pylist()
    return {a for a, i in zip(aids, iids) if i is None and a is not None}


def roster_seed_author_ids(roster_paths) -> set:
    """Extractor for the roster seed arm (a pure engineering fix):

    Roster author_ids are **injected directly** into the pass-A seeds. The root cause (a whole person missed
    during collection): a person in the roster has a verified author_id, but the institution fold of their
    snapshot bylines never hit the department boundary (the byline has no institution / the institution
    does not fold to the department) → pass-A fails to recognise the seed → all of that person's works are
    permanently absent. A roster member is a verified in-department author, so seed eligibility should no
    longer depend on the single "byline hit" arm.
    Reads the author_id column of each roster parquet, drops None (a roster member without an id cannot enter
    the author pool), and dedups across schools.
    Neutral on identification criteria: it only widens the fetch scope (fetch more, miss nothing) and touches
    no identification criterion. This arm takes effect in the full AWS rerun.
    """
    import pyarrow.parquet as pq

    out: set = set()
    for p in roster_paths:
        col = pq.read_table(str(p), columns=["author_id"]).column("author_id")
        out |= {a for a in col.to_pylist() if a is not None}
    return out


def build_plan(snapshot_root, out_root, *, n_workers, bucket_row_cap, max_shards=None) -> dict:
    """dry_run plan (reads no full data, writes nothing): counts the shards and echoes the parameters.

    If max_shards is set, only the [first N shards after sorting] are taken (subset smoke test: the full run
    takes 18h and cannot be resumed, so first check the start-up path on a small handful, then run everything).
    """
    shards = discover_work_shards(snapshot_root)
    if max_shards is not None:
        shards = shards[:max_shards]
    return {
        "executed": False,
        "snapshot_root": str(snapshot_root),
        "out_root": str(out_root),
        "work_shard_count": len(shards),
        "max_shards": max_shards,
        "n_workers": n_workers,
        "bucket_row_cap": bucket_row_cap,
        "note": "dry_run: 未读全量、未落盘。--execute 显式开 + 前置(econ_dept_ids 真名册 / "
                "S2 reduce 内存修完 / 磁盘 preflight)满足才真跑。",
    }


def run_full(
    snapshot_root,
    out_root,
    *,
    registry: list[dict],
    econ_dept_ids: set,
    n_workers: int = 1,
    bucket_row_cap: int = DEFAULT_BUCKET_ROW_CAP,
    execute: bool = False,
    source_snapshot_merkle: Optional[str] = None,
    config_sha: Optional[str] = None,
    rule_version: Optional[str] = None,
    code_version: Optional[str] = None,
    reconcile: bool = False,
    reconcile_diff_tolerance=None,
    reconcile_manifest=None,
    # By default the full-run entry point runs compact+dedup (the A3 dedup guard):
    #   it was off by default and was nearly left off in a full run → the default is now True; tests/smoke runs
    #   that want it off must pass False explicitly.
    #   The smoke driver run_smoke_m1 does not pass this parameter → it inherits this default (the smoke run
    #   neither forces it nor adds a CLI knob).
    run_compact_dedup: bool = True,
    # Wiring (b): the author_ids of byline hits with an empty institution
    #   are merged into the pass-A seeds (extractor = byline_empty_inst_seed_authors; fed by the driver layer).
    extra_seed_authors: Optional[set] = None,
    # ★Roster seed arm: list of roster parquet paths → author_ids injected directly into the
    #   pass-A seeds (extracted by roster_seed_author_ids, passed through as a union with extra_seed_authors;
    #   fixes the whole-person-missed case). None = arm off (existing runs are unchanged).
    roster_seed_paths: Optional[list] = None,
    max_shards: Optional[int] = None,
    pass_a_ckpt_dir: Optional[str] = None,
    scan_workers: int = 1,
    pass_a_checkpoint_every_n: int = 100,
    # The reduce stage runs per bucket in parallel: the final merge of 256 buckets x 5 tables is the largest remaining bottleneck after tuning (~45%).
    #   0 = auto (min(cpu, bucket count), production default uses all cores); 1 = serial, the old behaviour; positive = explicit concurrency. Buckets are independent → byte-identical results.
    reduce_workers: int = 0,
) -> dict:
    """Full-run driver. execute=False (default) → only emits the plan and writes nothing (safe).
    execute=True → really runs run_m1_streaming (hours / 696GB; its preconditions must be met and it needs approval).
    If max_shards is set, only the first N shards run (subset smoke test; the full run takes 18h and cannot be resumed, so first check the start-up path on a small handful, then run everything).

    ★A2 counter-anchor: turning reconcile=True on requires the operator to pass reconcile_manifest (the parsed
      top-level manifest object; see m0_snapshot.manifest_reconcile.parse_top_manifest) — expected is taken from
      the external truth of its works record_count, so a silent loss of records can be detected. This thin
      assembly layer does not load the manifest itself (the operator, or a future manifest-loading step, provides it).
    ★A3 dedup guard: run_compact_dedup defaults to True → at the end compact_dedup runs on every table
      (a duplicate PK → exit 21). To turn it off it must be passed False explicitly (same for tests/smoke runs); the guard is a
      read-only check and does not change the reconciliation semantics (tolerance / identity / manifest external anchor untouched).
      (The reconcile_scanned_shards shard arm is DEFERRED — see the note inside run_m1_streaming: the s3:// manifest and the local scan paths
      have different key spaces, and whole-shard completeness is M0's job.)"""
    plan = build_plan(snapshot_root, out_root, n_workers=n_workers,
                      bucket_row_cap=bucket_row_cap, max_shards=max_shards)
    # ★Roster seed arm: roster author_id extraction → union with the byline extra seeds (the two arms complement each other and are not exclusive).
    roster_seeds = roster_seed_author_ids(roster_seed_paths) if roster_seed_paths else set()
    merged_extra = set(extra_seed_authors or ()) | roster_seeds
    # Verifiable display for wiring (b) + the roster arm: the plan echoes the seed count per arm before launch (the operator knows the order of magnitude).
    plan["extra_seed_author_count"] = len(merged_extra)
    plan["roster_seed_author_count"] = len(roster_seeds)
    if not execute:
        return plan

    # Scale-up discipline (the A2 counter-anchor moved up to the assembly layer): turning reconciliation on requires an external truth anchor.
    #   The engine (run_m1_streaming) has the same fail-fast; doing it here too = a missing anchor is refused first —
    #   no credentials, environment gate or shard discovery runs, and nothing is written (refuse rather than blow up halfway).
    if reconcile and reconcile_manifest is None:
        raise ValueError(
            "scale-up discipline (#8/A2): execute=True with reconcile=True must pass reconcile_manifest "
            "as the external truth anchor (the parsed top-level manifest) — without it the reconciliation uses its own scanned counts as the expected counts, a false reconciliation; refusing to run."
        )

    # Hard-check the reproducibility values before a real run (None = placeholder → error; placeholders never pollute the reproducibility anchor of run_manifest).
    missing = [n for n, v in [
        ("source_snapshot_merkle", source_snapshot_merkle), ("config_sha", config_sha),
        ("rule_version", rule_version), ("code_version", code_version),
    ] if v is None]
    if missing:
        raise ValueError(f"execute=True requires real reproducibility credentials to be filled in explicitly, missing: {missing} (never run for real with placeholders)")

    # Pre-run environment check wiring (A11): the first gate of a real execute run.
    #   Four checks = pinned pyarrow version / OpenAlex key / redlines SHA / rapidfuzz; if any fails →
    #   SystemExit(ENVIRONMENT_GATE_FAIL=30) and no data is written (preflight_result.json is the gate's own
    #   audit record, always written in both cases following the U0 preflight pattern, so it does not count as a data product). dry_run does no check.
    from common.preflight import preflight_env_check
    _pf_dir = Path(out_root) / "_manifest"
    _pf_dir.mkdir(parents=True, exist_ok=True)
    _pf_rc = preflight_env_check(result_path=_pf_dir / "preflight_result.json")
    if _pf_rc != 0:
        raise SystemExit(_pf_rc)

    shards = discover_work_shards(snapshot_root)
    if max_shards is not None:
        shards = shards[:max_shards]
    # seed and pass-C share a source (the works the frontier points to are also in the full snapshot); ShardPathSource reopens the stream on every pass of __iter__.
    manifests = run_m1_streaming(
        ShardPathSource(shards), ShardPathSource(shards),
        registry=registry, econ_dept_ids=econ_dept_ids,
        out_root=out_root, n_workers=n_workers, bucket_row_cap=bucket_row_cap,
        source_snapshot_merkle=source_snapshot_merkle, config_sha=config_sha,
        rule_version=rule_version, code_version=code_version,
        reconcile=reconcile, reconcile_diff_tolerance=reconcile_diff_tolerance,
        reconcile_manifest=reconcile_manifest,
        run_compact_dedup=run_compact_dedup,
        extra_seed_authors=merged_extra,
        pass_a_ckpt_dir=pass_a_ckpt_dir,
        scan_workers=scan_workers,
        pass_a_checkpoint_every_n=pass_a_checkpoint_every_n,
        reduce_workers=reduce_workers,
    )
    return {"executed": True, "out_root": str(out_root),
            "tables": {k: len(v) for k, v in manifests.items()}}


def _build_arg_parser() -> argparse.ArgumentParser:
    """CLI: accepts only path / concurrency / execute switches — no identification-criterion flags (criteria are set by the red lines, not on the command line)."""
    p = argparse.ArgumentParser(description="U1-M1 full driver (dry_run by default; --execute runs for real and needs manual approval)")
    p.add_argument("--snapshot-root", required=True, help="OpenAlex snapshot root (contains works/)")
    p.add_argument("--out-root", required=True, help="root for the narrow tables (derived directory on SSD, not in git)")
    p.add_argument("--n-workers", type=int, default=1)
    p.add_argument("--bucket-row-cap", type=int, default=DEFAULT_BUCKET_ROW_CAP)
    p.add_argument("--execute", action="store_true",
                   help="run for real (hours / 696GB); if omitted, dry_run only prints the plan")
    return p


if __name__ == "__main__":
    _args = _build_arg_parser().parse_args()
    # __main__ only emits the dry_run plan: a real --execute full run needs registry/econ_dept_ids (the real roster) to be supplied inside a script
    #   (the real roster is not built yet = a full-run BLOCKER) + real reproducibility values, so running the CLI directly only prints the plan and never starts a real run (rule: a full large run must be approved by a person).
    _plan = build_plan(_args.snapshot_root, _args.out_root,
                       n_workers=_args.n_workers, bucket_row_cap=_args.bucket_row_cap)
    if _args.execute:
        _plan["note"] = ("⚠️ --execute 已请求, 但全量真跑需脚本内提供 registry + econ_dept_ids(真名册) "
                         "+ 真复现凭证; CLI 直跑仅出 plan。编程入口见 run_full()。")
    print(json.dumps(_plan, ensure_ascii=False, indent=2))
