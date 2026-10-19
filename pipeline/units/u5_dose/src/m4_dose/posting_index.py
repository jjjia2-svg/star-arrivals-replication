"""m4_dose/posting_index.py — year-partitioned inverted-index helper (H4).

posting_by_year/ = referenced_work_id -> (citing_work_id, publication_year) inverted index,
hive-partitioned by publication_year, canonical-sorted by (referenced_work_id, citing_work_id) within each partition.

H4: refs_edges itself has **no year** — publication_year always comes from works (join key = citing
work_id = refs_edges.work_id renamed); a citing work with no year -> PostingYearMissing (fail loud).
Hub refs are dropped by the RED threshold: ref weight <= idf_floor (dose.hub_ref_idf_floor, passed in by the calling layer) ->
not put in the index (a weight-0 hub contributes nothing to coupling, so dropping it speeds up the path and shrinks the index).
Position: an acceleration helper for the main dose, not the main path — the main path = direct computation by coupling.person_refs_until.
"""
from __future__ import annotations

import pathlib

from m1_ingest._writer_util import write_rows_parquet

# Inverted-index row schema (a U5 auxiliary product, local literal — not a U0 registry table).
# Standard hive layout: publication_year lives only in the partition directory name (publication_year=YYYY/)
# and is not stored again inside the file (avoids a clash between the partition key and a same-named column
# when the dataset is read back); reading the root directory with the dataset API restores the publication_year column automatically.
POSTING_ROW: dict[str, str] = {
    "referenced_work_id": "str",
    "citing_work_id": "str",
}


class PostingYearMissing(ValueError):
    """The citing work has no publication_year in works — H4: the only source of the year is works."""


def build_posting_by_year(refs_rows, works_by_id: dict, out_root, *,
                          ref_idf: dict | None, idf_floor: float) -> dict:
    """Build the inverted-index partitions (deterministic write) and return a {year: n_rows} summary.

    Args:
        refs_rows:  refs_edges rows {work_id, referenced_work_id} (no year, H4).
        works_by_id: {work_id: works row} — the only source of publication_year.
        out_root:   root of posting_by_year/ (hive directories publication_year=YYYY/).
        ref_idf:    IDF weight table (None = do not drop hubs); idf_floor: drop threshold (weight <= threshold -> dropped).
    """
    by_year: dict[int, list] = {}
    for r in refs_rows:
        citing = r["work_id"]
        ref = r["referenced_work_id"]
        if ref_idf is not None and ref_idf.get(ref, 0.0) <= idf_floor:
            continue  # drop hub refs by the RED threshold
        w = works_by_id.get(citing)
        if w is None or w.get("publication_year") is None:
            raise PostingYearMissing(
                f"posting: citing work {citing!r} has no publication_year in works "
                "(refs_edges has no year; the only year source is works; never silently dropped)"
            )
        year = w["publication_year"]
        by_year.setdefault(year, []).append({
            "referenced_work_id": ref,
            "citing_work_id": citing,
        })

    out_root = pathlib.Path(out_root)
    summary: dict[int, int] = {}
    for year in sorted(by_year):
        part_dir = out_root / f"publication_year={year}"
        write_rows_parquet(
            by_year[year],
            part_dir / "part-0.parquet",
            schema=POSTING_ROW,
            pk_cols=("referenced_work_id", "citing_work_id"),
            label=f"posting_by_year[{year}]",
        )
        summary[year] = len(by_year[year])
    return summary
