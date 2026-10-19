#!/usr/bin/env python3
"""01_scan_full_snapshot.py — full-snapshot FWCI denominator baseline scanner

Why (one sentence): the current `fwci_baseline_pop` only accumulates "seed-related" works
(`u1_fetch/src/m1_ingest/stream_build.py:289-302` — `if not is_relevant: continue`
happens before `fwci.add(work)`), so a self-built FWCI of "1.0" stands for the average level of
this network itself, not the world level. The full-snapshot field benchmark is used instead.

What this script does:
  Scans all 2,446 .gz shards (510,372,821 records) of the works data in the frozen OpenAlex snapshot
  (2026-06-26 release), **feeding every record to `FwciPopAccumulator`** (the production class itself, no
  seed / field / whitelist filter), accumulating work_count / citation_sum / cit_hist_32 per
  (subfield_id, year, work_type) cell.

The only difference from the current pop table is the population (full snapshot vs seed subset).
The accumulation logic reuses the production code line for line:
  - `m1_ingest.fwci_accumulator.FwciPopAccumulator` (red test test_add_covers_all_works_not_only_seed)
  - `m1_ingest.schema_map._subfield_id` (last segment of the primary_topic.subfield.id URL, single source of truth)
This script does **not rewrite** any cell assignment / counting / bucketing logic.

Two extra fields (absent from the current pop table, which made the paratext symmetric exclusion impossible on the denominator side):
  - paratext_count / paratext_citation_sum: number of is_paratext=True papers and their citation sum in each cell.
  They use the **same branch condition** as the main count (same _subfield_id / publication_year /
  type / cited_by_count), so they are a true subset of the main count and can be subtracted directly
  for the symmetric exclusion. The other 6 schema fields match the current pop table field for field.

Output (written to the new directory only; no existing table is touched):
  data/fwci_baseline_pop_full.parquet — 8-column cell table
  data/scan_manifest.json             — reconciliation voucher (record_count checked shard by shard)
  partial/task_XXXX.parquet + .json   — partial outputs for resuming (restart skips them)

Parallelism and resuming:
  - A task = a group of shards (packed by compressed bytes, default ~1.5 GB/task) -> about 440 tasks.
  - Each task writes partial/task_XXXX.{parquet,json} as soon as it finishes; after a restart the main process skips finished tasks.
  - The main process adds element by element (work_count / citation_sum / cit_hist_32 / paratext_* are all additive).

Usage:
  python3 01_scan_full_snapshot.py --workers 13
  python3 01_scan_full_snapshot.py --merge-only          # only merge existing partials
  python3 01_scan_full_snapshot.py --shards 3 --workers 3 --tag smoke   # smoke test
"""
from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

# --- M3 port: repo path resolution (legacy hard-coded the author's machine) — config/paths.yaml ---
import pathlib as _sar_pl, sys as _sar_sys
_sar_repo = next(p for p in _sar_pl.Path(__file__).resolve().parents if p.name == "fwci").parents[1]
if str(_sar_repo) not in _sar_sys.path:
    _sar_sys.path.append(str(_sar_repo))
from pipeline.lib.paths import (derived_root as _sar_derived_root,  # noqa: E402,F401
                                snapshot_root as _sar_snapshot_root,
                                ssd_root as _sar_ssd_root,
                                legacy_thesis as _sar_legacy_thesis,
                                require_readable as _sar_rd,
                                require_writable as _sar_rw,
                                output_target as _sar_out,
                                deferred_output_target as _sar_lazyout)

# --- Path wiring: reuse the u0 common + u1 m1_ingest production code ---
ROOT = str(_sar_rd(_sar_legacy_thesis()))
sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u0_foundation/src")
sys.path.insert(0, f"{ROOT}/multiplex_pipeline/units/u1_fetch/src")

from m1_ingest.fwci_accumulator import (  # noqa: E402  the production code itself
    FwciPopAccumulator,
    N_CIT_BUCKETS,
)
from m1_ingest.schema_map import _subfield_id as _subfield_id_from_work  # noqa: E402

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

SNAPSHOT = Path(str(_sar_rd(_sar_snapshot_root())))
BASE = Path(__file__).resolve().parent.parent
PARTIAL_DIR = BASE / "partial"
DATA_DIR = BASE / "data"
LOG_DIR = BASE / "logs"

# JSON parser: orjson (~3x faster); --json-lib stdlib switches back to the standard library for an equivalence check.
_JSON_LIB = "orjson"
try:
    import orjson as _orjson  # noqa: E402

    _loads = _orjson.loads
except Exception:  # pragma: no cover
    _orjson = None
    _loads = json.loads
    _JSON_LIB = "stdlib"


def set_json_lib(name: str) -> None:
    """Switch the JSON parser (for the equivalence check). Both must produce the same dict for the same line."""
    global _loads, _JSON_LIB
    if name == "stdlib":
        _loads, _JSON_LIB = json.loads, "stdlib"
    elif name == "orjson":
        if _orjson is None:
            raise SystemExit("orjson is not installed")
        _loads, _JSON_LIB = _orjson.loads, "orjson"
    else:
        raise SystemExit(f"unknown json-lib: {name}")


class FwciPopAccumulatorPlus(FwciPopAccumulator):
    """Production accumulator + per-cell paratext counts.

    ★The main count goes 100% through `super().add(work)` (the production code itself, not one line changed).
    This subclass only **additionally** records paratext (count, citation_sum), with a branch condition
    identical to the parent's add: the same `_subfield_id_from_work` / `publication_year` / `type` /
    `cited_by_count or 0`, and when subfield/year is missing the work likewise does not enter a cell
    (the parent counts dropped_null; here it is skipped the same way).
    -> the paratext counts are always a true subset of the main count in the same cell, so downstream
    can apply the symmetric exclusion directly (denominator minus paratext).
    """

    def __init__(self) -> None:
        super().__init__()
        # key -> [paratext_count, paratext_citation_sum]
        self.para_cells: dict[tuple, list[int]] = {}
        # G-A breakdown of missing reasons: the parent only gives the total dropped_null; here it is split into three kinds (parent counts unchanged)
        self.drop_no_subfield: int = 0
        self.drop_no_year: int = 0
        self.drop_both: int = 0

    def add(self, work: dict) -> None:
        super().add(work)                      # <- main count: the production code itself, unchanged
        subfield_id = _subfield_id_from_work(work)
        year = work.get("publication_year")
        if subfield_id is None or year is None:
            # Exactly the same branch as the parent's dropped_null, only split into three kinds (their sum always equals the parent's dropped_null)
            if subfield_id is None and year is None:
                self.drop_both += 1
            elif subfield_id is None:
                self.drop_no_subfield += 1
            else:
                self.drop_no_year += 1
            return
        if not work.get("is_paratext"):
            return
        key = (subfield_id, int(year), work.get("type"))
        cited = int(work.get("cited_by_count") or 0)
        e = self.para_cells.get(key)
        if e is None:
            self.para_cells[key] = [1, cited]
        else:
            e[0] += 1
            e[1] += cited


# ---------------------------------------------------------------- shard list

def load_shards() -> list[dict]:
    """Read the 2,446 works shards from the snapshot manifest.json (with the official record_count / content_length).

    The manifest is the snapshot's authoritative ledger: the shard-level record_count lets G-A
    reconcile down to the shard, not "roughly". Local path = the url with the s3 prefix up to and
    including data/jsonl/ removed.
    """
    m = json.loads((SNAPSHOT / "manifest.json").read_text())
    works = [e for e in m["entities"] if e["entity"] == "works"][0]
    out = []
    for i, f in enumerate(works["files"]):
        rel = f["url"].split("/data/jsonl/", 1)[1]
        out.append({
            "idx": i,
            "rel": rel,
            "path": str(SNAPSHOT / rel),
            "record_count": f["meta"]["record_count"],
            "content_length": f["meta"]["content_length"],
        })
    assert sum(s["record_count"] for s in out) == works["record_count"], "manifest self-consistency check failed"
    return out


def pack_tasks(shards: list[dict], bytes_per_task: int) -> list[list[dict]]:
    """Pack shards into tasks by compressed bytes (greedy, in order: deterministic and resumable).

    A single shard larger than the pack size becomes a task of its own (shards are not split, to avoid cutting a gz mid-stream).
    """
    tasks, cur, cur_b = [], [], 0
    for s in shards:
        if cur and cur_b + s["content_length"] > bytes_per_task:
            tasks.append(cur)
            cur, cur_b = [], 0
        cur.append(s)
        cur_b += s["content_length"]
    if cur:
        tasks.append(cur)
    return tasks


# ---------------------------------------------------------------- worker

_PARTIAL_SCHEMA = pa.schema([
    ("subfield_id", pa.string()),
    ("year", pa.int64()),
    ("work_type", pa.string()),
    ("work_count", pa.int64()),
    ("citation_sum", pa.int64()),
    ("cit_hist_32", pa.list_(pa.int64(), N_CIT_BUCKETS)),
    ("paratext_count", pa.int64()),
    ("paratext_citation_sum", pa.int64()),
])


def _acc_to_arrow(acc: FwciPopAccumulatorPlus) -> pa.Table:
    """Accumulator internal state -> arrow table (deterministic sort, None-safe, same key order as the production to_table)."""
    keys = sorted(acc._cells, key=lambda k: (k[0], k[1], k[2] is None, "" if k[2] is None else k[2]))
    sf, yr, wt, wc, cs, hist, pc, ps = [], [], [], [], [], [], [], []
    for k in keys:
        cell = acc._cells[k]
        p = acc.para_cells.get(k, (0, 0))
        sf.append(k[0]); yr.append(k[1]); wt.append(k[2])
        wc.append(cell.work_count); cs.append(cell.citation_sum)
        hist.append(list(cell.hist))
        pc.append(p[0]); ps.append(p[1])
    return pa.Table.from_arrays(
        [pa.array(sf, pa.string()), pa.array(yr, pa.int64()), pa.array(wt, pa.string()),
         pa.array(wc, pa.int64()), pa.array(cs, pa.int64()),
         pa.array(hist, pa.list_(pa.int64(), N_CIT_BUCKETS)),
         pa.array(pc, pa.int64()), pa.array(ps, pa.int64())],
        schema=_PARTIAL_SCHEMA)


def run_task(job: tuple) -> dict:
    """Process one task (a group of shards) -> write partial/task_XXXX.{parquet,json}, return diagnostics.

    ★Every works record goes through acc.add(work) with no filtering — this is the only difference from the current pop table.
    """
    tid, shards, tag, json_lib = job
    if json_lib != _JSON_LIB:
        set_json_lib(json_lib)
    t0 = time.time()
    acc = FwciPopAccumulatorPlus()
    n_lines = 0
    n_bad = 0
    per_shard = []
    for s in shards:
        c0 = n_lines
        with gzip.open(s["path"], "rb") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    work = _loads(line)
                except Exception:
                    n_bad += 1          # bad lines are counted loudly, never silently treated as 0 records
                    continue
                acc.add(work)           # <- everything is fed in, no seed / field filter
                n_lines += 1
        per_shard.append({"rel": s["rel"], "read": n_lines - c0,
                          "manifest": s["record_count"]})

    tbl = _acc_to_arrow(acc)
    pq.write_table(tbl, PARTIAL_DIR / f"{tag}task_{tid:05d}.parquet", compression="zstd")
    diag = {
        "task_id": tid, "n_shards": len(shards), "n_lines": n_lines, "n_bad_lines": n_bad,
        "dropped_null": acc.dropped_null, "paratext_count": acc.paratext_count,
        "drop_no_subfield": acc.drop_no_subfield, "drop_no_year": acc.drop_no_year,
        "drop_both": acc.drop_both,
        "n_cells": tbl.num_rows, "elapsed_s": round(time.time() - t0, 1),
        "json_lib": _JSON_LIB, "per_shard": per_shard, "done": True,
    }
    (PARTIAL_DIR / f"{tag}task_{tid:05d}.json").write_text(json.dumps(diag))
    return {k: v for k, v in diag.items() if k != "per_shard"}


# ---------------------------------------------------------------- merge

def _partial_keys(f: Path) -> list[tuple]:
    t = pq.read_table(f, columns=["subfield_id", "year", "work_type"])
    return list(zip(t.column(0).to_pylist(), t.column(1).to_pylist(), t.column(2).to_pylist()))


def merge(tag: str, out_parquet: Path) -> dict:
    """Add all partials element by element -> total table. work_count/citation_sum/hist/paratext are all additive.

    Two passes (pure int64 addition, no floats -> bit-identical to a serial single-process scan):
      pass-1 reads only the three key columns -> builds the global cell index (deterministic sort).
      pass-2 numpy fancy-index accumulation (keys are unique within a partial, so `arr[idx] += part` has no duplicate-index problem).
    """
    import numpy as np

    files = sorted(PARTIAL_DIR.glob(f"{tag}task_*.parquet"))
    tot_lines = tot_bad = tot_dropped = tot_para = 0
    d_nosf = d_noyr = d_both = 0
    per_shard_read: dict[str, int] = {}
    all_keys: set[tuple] = set()
    for i, f in enumerate(files):
        d = json.loads(f.with_suffix(".json").read_text())
        tot_lines += d["n_lines"]; tot_bad += d["n_bad_lines"]
        tot_dropped += d["dropped_null"]; tot_para += d["paratext_count"]
        d_nosf += d.get("drop_no_subfield", 0); d_noyr += d.get("drop_no_year", 0)
        d_both += d.get("drop_both", 0)
        for ps in d["per_shard"]:
            per_shard_read[ps["rel"]] = per_shard_read.get(ps["rel"], 0) + ps["read"]
        all_keys.update(_partial_keys(f))
        if (i + 1) % 50 == 0:
            print(f"[merge/keys] {i+1}/{len(files)} cells={len(all_keys):,}", flush=True)

    keys = sorted(all_keys, key=lambda k: (k[0], k[1], k[2] is None, "" if k[2] is None else k[2]))
    kidx = {k: i for i, k in enumerate(keys)}
    n = len(keys)
    wc = np.zeros(n, dtype=np.int64)
    cs = np.zeros(n, dtype=np.int64)
    hh = np.zeros((n, N_CIT_BUCKETS), dtype=np.int64)
    pc = np.zeros(n, dtype=np.int64)
    ps_ = np.zeros(n, dtype=np.int64)

    for i, f in enumerate(files):
        t = pq.read_table(f)
        ks = list(zip(t.column("subfield_id").to_pylist(), t.column("year").to_pylist(),
                      t.column("work_type").to_pylist()))
        if len(set(ks)) != len(ks):
            raise SystemExit(f"HALT: partial {f.name} primary key not unique — the fancy-index accumulation needs unique keys")
        idx = np.fromiter((kidx[k] for k in ks), dtype=np.int64, count=len(ks))
        wc[idx] += np.asarray(t.column("work_count").to_numpy(zero_copy_only=False), dtype=np.int64)
        cs[idx] += np.asarray(t.column("citation_sum").to_numpy(zero_copy_only=False), dtype=np.int64)
        flat = t.column("cit_hist_32").combine_chunks().flatten().to_numpy(zero_copy_only=False)
        hh[idx] += flat.astype(np.int64).reshape(len(ks), N_CIT_BUCKETS)
        pc[idx] += np.asarray(t.column("paratext_count").to_numpy(zero_copy_only=False), dtype=np.int64)
        ps_[idx] += np.asarray(t.column("paratext_citation_sum").to_numpy(zero_copy_only=False),
                               dtype=np.int64)
        if (i + 1) % 50 == 0:
            print(f"[merge/sum] {i+1}/{len(files)}", flush=True)

    # Internal-consistency hard check (accumulator invariant; must still hold after the merge)
    bad_hist = int((hh.sum(axis=1) != wc).sum())
    if bad_hist:
        raise SystemExit(f"HALT: number of cells where the cit_hist_32 bucket sum != work_count = {bad_hist}")
    if int((pc > wc).sum()) or int((ps_ > cs).sum()):
        raise SystemExit("HALT: paratext count exceeds the main count — not a true subset")

    tbl = pa.Table.from_arrays(
        [pa.array([k[0] for k in keys], pa.string()),
         pa.array([k[1] for k in keys], pa.int64()),
         pa.array([k[2] for k in keys], pa.string()),
         pa.array(wc, pa.int64()), pa.array(cs, pa.int64()),
         pa.FixedSizeListArray.from_arrays(pa.array(hh.reshape(-1), pa.int64()), N_CIT_BUCKETS),
         pa.array(pc, pa.int64()), pa.array(ps_, pa.int64())],
        schema=_PARTIAL_SCHEMA)
    pq.write_table(tbl, out_parquet, compression="zstd")
    if d_nosf + d_noyr + d_both != tot_dropped:
        raise SystemExit("HALT: the three-way breakdown of missing reasons does not sum to dropped_null")
    return {"n_cells": n, "n_partials": len(files), "total_lines_read": tot_lines,
            "bad_lines": tot_bad, "dropped_null": tot_dropped, "paratext_count": tot_para,
            "drop_no_subfield": d_nosf, "drop_no_year": d_noyr, "drop_no_both": d_both,
            "sum_work_count": int(wc.sum()), "sum_citation_sum": int(cs.sum()),
            "sum_paratext_count": int(pc.sum()), "sum_paratext_citation_sum": int(ps_.sum()),
            "per_shard_read": per_shard_read}


# ---------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=13)
    ap.add_argument("--bytes-per-task", type=int, default=1_500_000_000)
    ap.add_argument("--shards", type=int, default=0, help="run only the first N shards (for smoke tests; 0 = all)")
    ap.add_argument("--shard-list", type=str, default="", help="comma-separated shard indices (for smoke tests)")
    ap.add_argument("--tag", type=str, default="", help="prefix of the partial file names (keeps smoke-test output separate)")
    ap.add_argument("--json-lib", type=str, default="orjson", choices=["orjson", "stdlib"])
    ap.add_argument("--merge-only", action="store_true")
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()

    tag = (args.tag + "_") if args.tag else ""
    out_parquet = Path(args.out) if args.out else DATA_DIR / f"{tag}fwci_baseline_pop_full.parquet"
    PARTIAL_DIR.mkdir(exist_ok=True); DATA_DIR.mkdir(exist_ok=True); LOG_DIR.mkdir(exist_ok=True)

    shards = load_shards()
    if args.shard_list:
        want = {int(x) for x in args.shard_list.split(",")}
        shards = [s for s in shards if s["idx"] in want]
    elif args.shards:
        shards = shards[: args.shards]
    manifest_records = sum(s["record_count"] for s in shards)
    print(f"[scan] shards={len(shards)} manifest_records={manifest_records:,} "
          f"gz_bytes={sum(s['content_length'] for s in shards):,}", flush=True)

    tasks = pack_tasks(shards, args.bytes_per_task)
    print(f"[scan] tasks={len(tasks)} workers={args.workers} json_lib={args.json_lib}", flush=True)

    if not args.merge_only:
        todo = []
        for tid, t in enumerate(tasks):
            jf = PARTIAL_DIR / f"{tag}task_{tid:05d}.json"
            pf = PARTIAL_DIR / f"{tag}task_{tid:05d}.parquet"
            if jf.exists() and pf.exists():
                try:
                    if json.loads(jf.read_text()).get("done"):
                        continue            # Resume after interruption: skip finished tasks
                except Exception:
                    pass
            todo.append((tid, t, tag, args.json_lib))
        print(f"[scan] todo={len(todo)}/{len(tasks)} (resume skipped {len(tasks)-len(todo)})",
              flush=True)

        t0 = time.time()
        done_lines = 0
        if todo:
            ctx = mp.get_context("fork")
            with ctx.Pool(args.workers) as pool:
                for n, r in enumerate(pool.imap_unordered(run_task, todo), 1):
                    done_lines += r["n_lines"]
                    el = time.time() - t0
                    rate = done_lines / el if el else 0
                    eta = (len(todo) - n) * (el / n) / 60 if n else 0
                    print(f"[scan] {n}/{len(todo)} task={r['task_id']} lines={r['n_lines']:,} "
                          f"cells={r['n_cells']:,} {r['elapsed_s']}s | cum={done_lines:,} "
                          f"{rate:,.0f} rec/s | ETA {eta:.1f} min", flush=True)
        print(f"[scan] scan done in {(time.time()-t0)/60:.1f} min", flush=True)

    print("[merge] merging partials …", flush=True)
    t1 = time.time()
    res = merge(tag, out_parquet)
    per_shard_read = res.pop("per_shard_read")

    # --- G-A reconciliation voucher: shard-level read vs manifest ---
    mismatch = [{"rel": s["rel"], "manifest": s["record_count"], "read": per_shard_read.get(s["rel"], 0)}
                for s in shards if per_shard_read.get(s["rel"], 0) != s["record_count"]]
    res.update({
        "manifest_record_count": manifest_records,
        "shards": len(shards),
        "shard_read_mismatches": len(mismatch),
        "shard_read_mismatch_examples": mismatch[:20],
        "lines_read_equals_manifest": res["total_lines_read"] + res["bad_lines"] == manifest_records,
        "merge_elapsed_min": round((time.time() - t1) / 60, 2),
        "out_parquet": str(out_parquet),
        "snapshot_manifest_date": json.loads((SNAPSHOT / "manifest.json").read_text())["date"],
        "json_lib": args.json_lib,
    })
    (DATA_DIR / f"{tag}scan_manifest.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in res.items() if k != "shard_read_mismatch_examples"},
                     indent=1, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
