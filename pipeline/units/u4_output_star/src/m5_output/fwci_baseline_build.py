"""M5-T0: derive the expected baseline (FWCI denominator, schema.py [24]) from FWCI_BASELINE_POP.

In plain words: divide the U1 counts of "how many papers and how many citations in total each (subfield x year x type) pool has",
giving "the average citations of a paper in this pool"; each later paper's quality score = its own citations / this average.

Rules (all fixed; this module only consumes them):
  - expected_method=mean: expected = citation_sum / work_count (the 32-bucket version is void, cit_hist_32 is not read)
  - included_types=[article,review]: the denominator keeps only these two types (B-SYM: same source and same list as the numerator)
  - denominator_leave_star=false: the denominator includes the full star set (this module does not know who the stars are)
  - subfield all None -> HALT (C-4, guards against snapshot fallback)
Note, import guard (B16/isc#2): this node does not import aggregate_output and does not read is_star_coauthored.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from common._redlines import RED, require
from identity.output_rule import fwci_baseline_contribution


def build_fwci_baseline(pop_rows: list[dict]) -> list[dict]:
    """FWCI_BASELINE_POP rows -> FWCI_BASELINE 4-column rows (pure function, deterministic ordering)."""
    included = set(require("fwci", "included_types"))

    if pop_rows and all(r.get("subfield_id") is None for r in pop_rows):
        sys.stderr.write(
            "[U4/M5-T0] subfield_id is None for all of FWCI_BASELINE_POP — snapshot fallback or broken upstream, "
            "the self-built FWCI denominator cannot be formed → HALT\n"
        )
        sys.exit(2)

    out = []
    for r in pop_rows:
        if r["work_type"] not in included:
            continue  # R1 whitelist: the denominator drops the same types as the numerator (B-SYM)
        out.append({
            "subfield_id": r["subfield_id"],
            "year": r["year"],
            "work_type": r["work_type"],
            "expected_citations": r["citation_sum"] / r["work_count"],
        })
    out.sort(key=lambda r: (str(r["subfield_id"]), r["year"], str(r["work_type"])))
    return out


def rebuild_leave_star_baseline(works_rows: list[dict], star_work_ids: set[str],
                                cells: set[tuple]) -> list[dict]:
    """Leave-star baseline: only for the affected cells, recompute expected from the works table after excluding star works.

    No conflict with "the denominator does not exclude stars": the global baseline (build_fwci_baseline) always includes the full set;
    this function only builds a control baseline for "cohorts affected by some star's arrival", on a small scale with an explicitly passed cell set.
    Reuses identity.output_rule.fwci_baseline_contribution (T35 isolation: reads only four fields, knows nothing about isc);
    its work dict uses the `year` key -> here mapped explicitly from the works table `publication_year` (B16 note).
    """
    included = set(require("fwci", "included_types"))
    acc: dict[tuple, list[int]] = {}
    for w in works_rows:
        if w["work_id"] in star_work_ids:
            continue  # Star works are excluded: this is the definition of leave-star
        if w["work_type"] not in included:
            continue  # B-SYM: same source and same list as the global denominator
        c = fwci_baseline_contribution({
            "subfield_id": w["subfield_id"], "year": w["publication_year"],
            "work_type": w["work_type"], "cited_by_count": w["cited_by_count"],
        })
        if c["key"] not in cells:
            continue
        acc.setdefault(c["key"], []).append(c["cited_by_count"])
    out = [{"subfield_id": k[0], "year": k[1], "work_type": k[2],
            "expected_citations": sum(v) / len(v)} for k, v in acc.items()]
    out.sort(key=lambda r: (str(r["subfield_id"]), r["year"], str(r["work_type"])))
    return out


def write_fwci_baseline(rows: list[dict], out_dir, *, source_snapshot_merkle: str = "",
                        config_sha: str = "") -> dict:
    """Write <out_dir>/data.parquet (U1 deterministic writer) + the manifest_header.json quadruple.

    - stars_set_hash is an empty-string placeholder (after M7a freezes, U5 injects it into its provenance; the key slot is already in place)
    - S8-2: snapshot_year is read from RED (null raises, via the require guard)
    - merkle/config_sha are injected by run_u4 orchestration (empty-string defaults at unit level, key slots present)
    """
    from common.schema import FWCI_BASELINE
    from m1_ingest._writer_util import write_rows_parquet

    out_dir = Path(out_dir)
    write_rows_parquet(rows, out_dir / "data.parquet", schema=FWCI_BASELINE,
                       pk_cols=("subfield_id", "year", "work_type"),
                       label="fwci_baseline")
    header = {
        "source_snapshot_merkle": source_snapshot_merkle,
        "config_sha": config_sha,
        "rule_version": RED.get("rule_version", ""),
        "stars_set_hash": "",
        "snapshot_year": require("fwci", "snapshot_year"),
        "table": "fwci_baseline",
    }
    hpath = out_dir / "manifest_header.json"
    hpath.write_text(json.dumps(header, ensure_ascii=False, sort_keys=True, indent=1),
                     encoding="utf-8")
    return header
