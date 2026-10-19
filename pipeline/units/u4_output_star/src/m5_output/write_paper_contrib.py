"""M5-T3 write_paper_contrib: deterministic 256-bucket write of paper_contrib.

In plain words: hash the paper_contrib rows expanded by M5-T1 into 256 buckets by primary key and write them out. A repeated primary key is written only
once; two runs on the same input are byte-equal (downstream resume compares sha). The dataset-level _frozen/COMMIT is written
by run_u4; this module only does the bucketed write of the single table paper_contrib + returns the manifest.

Rules (fixed; this module only consumes them):
  - 256-bucket HashBucketWriter (owner=U1, m1_ingest): canonical sort by PK + fixed parquet
    parameters (zstd / dictionary off / single row-group / no statistics / no schema embedded) -> deterministic bytes.
  - Derived invariant: rows written = number of distinct PKs = sum over works of distinct incumbent x person (M5-T1 fidelity).
  - isc#2 / B16 back-edge isolation: this writer does not import aggregate_output and does not reference is_star_coauthored as a
    code symbol (the isc column is written transparently as an ordinary paper_contrib column, but the FWCI path never reads it).

Pure IO layer: no identification thresholds, no network; writing goes through U1's only deterministic writer, no hand-built pyarrow.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from common.schema import PAPER_CONTRIB
from m1_ingest.hash_bucket_writer import HashBucketWriter

# paper_contrib primary key (schema [18] PK; granularity of the three-key cross product).
_PK = ("work_id", "incumbent_person_id", "person_id")


def dedup_by_pk(rows: Iterable[dict]) -> list[dict]:
    """De-duplicate by primary key (work_id, incumbent_person_id, person_id), keeping the first occurrence (deterministic).

    Same PK with an identical full-row payload -> idempotent dedup (harmless).
    Same PK with conflicting payload (fwci/isc etc. differ) -> raise with the work_id: the write is the last gate,
    and a disagreement is not erased silently (covers the unexpected case where upstream gives inconsistent values for one work).
    """
    seen: dict[tuple, dict] = {}
    out: list[dict] = []
    for r in rows:
        k = tuple(r[c] for c in _PK)
        if k in seen:
            if r != seen[k]:
                raise ValueError(
                    f"paper_contrib: two rows with the same primary key {k} have conflicting payloads "
                    f"(work {r['work_id']!r}) — upstream gave inconsistent fwci/isc etc. for the same work, "
                    "refusing to drop one silently; check the upstream dedup / FWCI computation"
                )
            continue  # Fully identical -> idempotent dedup
        seen[k] = r
        out.append(r)
    return out


def write_paper_contrib(rows: Iterable[dict], out_dir, *, n_buckets: int = 256) -> dict:
    """Write bucketed parquet under <out_dir>/paper_contrib/ and return the manifest + counts.

    Steps: materialise -> de-duplicate by PK -> add row by row to HashBucketWriter (schema guard built in) ->
    flush_all() returns the manifest (rel_path/sha256/row_count per part).

    Returns: {"manifest": list, "n_rows": rows written, "n_input": rows passed in,
           "n_dedup_dropped": rows dropped by dedup}.
    """
    materialized = [dict(r) for r in rows]
    deduped = dedup_by_pk(materialized)

    table_dir = Path(out_dir) / "paper_contrib"
    # Clear this table's old output (only the paper_contrib/ subdirectory; other tables in out_dir are untouched):
    # HashBucketWriter only appends to same-named rel_paths, so old bucket parts that are not hit become orphans -> glob ghost rows.
    # Clear the directory + atomic write -> disk always equals this run's manifest. A half-written crash has no COMMIT -> run_u4 resume rebuilds.
    if table_dir.exists():
        shutil.rmtree(table_dir)
    writer = HashBucketWriter(str(table_dir), schema=PAPER_CONTRIB,
                              pk_cols=_PK, n_buckets=n_buckets)
    for r in deduped:
        writer.add(r)
    manifest = writer.flush_all()

    n_rows = sum(m["row_count"] for m in manifest)
    return {
        "manifest": manifest,
        "n_rows": n_rows,
        "n_input": len(materialized),
        "n_dedup_dropped": len(materialized) - len(deduped),
    }
