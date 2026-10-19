"""M1-T-FP first_pub.py - WORK_FIRST_PUB table (true career first-publication year).

What it does:
  - accumulates the full publication history (pass-A scans every author x publication_year of every work);
  - per author, min(publication_year) = the true career first-publication year;
  - the min is taken after canonical folding: two raw ids of one person fold to one canonical id and the earlier first-publication
    year wins, so a split id never makes the year look later (test case: A_old 2003 / A_new 2010 -> 2003).
  - is_full_history=True (from a full-snapshot scan, not a truncated window).

Conventions:
  - the true career first-publication year (min over the full history) feeds PANEL.first_pub_year and is used for career-age / cohort grouping;
  - never use proxies such as affiliations[].years (that is the year of publishing at an institution,
    not the career start); this table reads only publication_year.

Official usage: OpenAlex publication_year.

Red line: pure data shape (take the min), no identification rule; canonical ids are looked up in cmap only, and a missing id stays as the bare id.
  Career-age binning / cohort grouping is itself part of the identification layer (placeholder, not set) and is not in this table -
  this table only produces the raw first_pub_year.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from common.schema import WORK_FIRST_PUB
from m1_ingest._writer_util import bare, write_rows_parquet


class FirstPubAccumulator:
    """Accumulate the full publication history -> the true career first-publication year (min publication_year) of each (canonical) author.

    author_cmap = {raw_id: canonical_id} (replay of M0 merged_ids); add() folds author_id to canonical
    and then accumulates -> the min is taken after folding.
    A None year is skipped (does not take part in the min); an author with only None years yields no row (no trustworthy first year).
    """

    def __init__(self, *, author_cmap: Optional[Mapping[str, str]] = None):
        self._cmap = author_cmap or {}
        self._min_year: dict[str, int] = {}  # canonical author_id → min year
        self._order: list[str] = []          # Insertion order (deterministic)

    def add(self, *, author_id, publication_year) -> None:
        if publication_year is None:
            return  # A None year does not take part in the min and does not raise
        cid = bare(author_id)
        if cid is None:
            return
        cid = self._cmap.get(cid, cid)
        y = int(publication_year)
        if cid not in self._min_year:
            self._min_year[cid] = y
            self._order.append(cid)
        elif y < self._min_year[cid]:
            self._min_year[cid] = y

    def load_rows(self, rows: Iterable[Mapping]) -> None:
        """Restore state from archived rows (author_id/first_pub_year) (resume foundation): reuses add() row by row,
        so continuing to add the remaining shards still gives the full-history min. Reusing add(): restore + continue == one full scan (min is commutative and associative)."""
        for r in rows:
            self.add(author_id=r["author_id"], publication_year=r["first_pub_year"])

    def iter_rows_chunks(self, chunk_size: int = 2_000_000):
        """Yield rows in chunks (for writing the archive): the accumulator holds ~all authors (tens of millions), so never materialise the whole table as one big list
        (that would be a ~10GB memory spike -> OOM on a 24GB machine). Chunked yield keeps the peak to one chunk."""
        chunk = []
        for cid in self._order:
            chunk.append({"author_id": cid, "first_pub_year": self._min_year[cid],
                          "first_pub_year_is_full_history": True})
            if len(chunk) >= chunk_size:
                yield chunk
                chunk = []
        if chunk:
            yield chunk

    def load_from_parquet(self, path, *, batch_size: int = 2_000_000) -> None:
        """Restore from a parquet archive as a stream (for resume): read in batches -> add one by one, never read the whole table into memory (avoids a memory spike and OOM).
        Missing file -> empty (nothing to restore). Reuses add(): restore + continue == full scan."""
        import pyarrow.parquet as pq
        from pathlib import Path as _P

        if not _P(path).exists():
            return
        pf = pq.ParquetFile(str(path))
        for batch in pf.iter_batches(batch_size=batch_size, columns=["author_id", "first_pub_year"]):
            aids = batch.column("author_id").to_pylist()
            yrs = batch.column("first_pub_year").to_pylist()
            for aid, y in zip(aids, yrs):
                self.add(author_id=aid, publication_year=y)

    def add_work(self, work: dict) -> None:
        """Convenience: every author of a work takes that work's publication_year (rides along with pass-A)."""
        year = work.get("publication_year")
        for authorship in work.get("authorships") or []:
            author_id = (authorship.get("author") or {}).get("id")
            self.add(author_id=author_id, publication_year=year)

    def rows(self) -> list[dict]:
        """Export the WORK_FIRST_PUB 3-column rows (insertion order; the writer sorts when writing)."""
        return [
            {
                "author_id": cid,
                "first_pub_year": self._min_year[cid],
                "first_pub_year_is_full_history": True,
            }
            for cid in self._order
        ]

    def write(self, target) -> None:
        write_first_pub(self.rows(), target)


def write_first_pub(rows: Iterable[dict], target) -> None:
    """Write the WORK_FIRST_PUB parquet (PK=author_id; deterministic, schema check before writing, exactly 3 columns)."""
    write_rows_parquet(
        rows, target,
        schema=WORK_FIRST_PUB,
        pk_cols=("author_id",),
        label="WORK_FIRST_PUB",
    )
