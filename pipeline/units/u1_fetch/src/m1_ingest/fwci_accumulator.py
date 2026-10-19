"""M1-T4 fwci_accumulator - sequential-scan accumulator for the self-built FWCI denominator population (FWCI_BASELINE_POP).

Why it is needed (fwci_baseline_pop rows + Work fields):
  FWCI (Field-Weighted Citation Impact = field-normalised citation ratio) is built in-house: we do not trust the OpenAlex native
  fwci but compute, inside the frozen snapshot, "a paper's citation count / the expectation of its (subfield, year, work_type) cell".
  This accumulator produces only the raw material of the denominator population: over all scanned works, per (subfield_id, year, work_type)
  cell it accumulates work_count + citation_sum + a 32-bucket log citation histogram. The self-built denominator needs only
  cited_by_count + subfield_id (cited_by_count is an int; the native fwci is not needed).

What this accumulator does:
  - log_bucket_index(c): put cited_by_count into a 32-bucket log histogram (0..31, monotone, deterministic integer arithmetic).
  - FwciPopAccumulator.add(work): scan one works record -> accumulate into its cell (covers ALL works: no
    seed / economics-department whitelist filtering, that belongs to the pass layer). Missing subfield/year -> dropped_null diagnostic count.
  - .to_table(): produce FWCI_BASELINE_POP 6-key rows sorted by (subfield_id, year, work_type) (deterministic).

Boundary of the identification rules (this module never decides them):
  - snapshot_year = null (placeholder, not set) -> require_snapshot_year() raises RedlineUnsigned as soon as it is read.
    This accumulator produces "window-independent population counts" (work_count/citation_sum/histogram) and does not depend on the snapshot year;
    snapshot_year is the "citation-window anchor used downstream when computing the FWCI ratio"; that step is unset -> the placeholder stays
    and the accumulator never peeks.
  - Values that are set in redlines.yaml are only restated here: field_level=subfield / expected_method=mean
    (the 32-bucket quantile method is discarded; cit_hist_32 is only a diagnostic / robustness carrier) /
    included_types=[article,review] (U1 does not filter, it only supplies).
  - paratext: paratext_symmetric_drop is set -> the symmetric drop is done downstream; this table still accumulates per cell and counts paratext_count
    as a diagnostic, and never drops anything in the accumulation layer (to avoid drifting from the downstream rule).

Reuses U0, no rewrite:
  - common.schema.{FWCI_BASELINE_POP, assert_matches_schema} (exactly 6 keys before writing).
  - common._redlines.require (reads set literals; null -> RedlineUnsigned, never a silent default).
  - Parquet writing is done by run_m1 / HashBucketWriter; this module only produces validated in-memory rows (deterministically sorted).

Discipline: pure accumulation logic, no network / no disk reads / no invented identification rules.
"""
from __future__ import annotations

from typing import Any, Iterator

from common._redlines import require
from common.schema import FWCI_BASELINE_POP, assert_matches_schema

# subfield_id extraction (last segment of the primary_topic.subfield.id URL; guards against a silent 0 rows from ==int): reuses the
#   single authoritative implementation in schema_map (_subfield_id) instead of a second copy. Re-exported under a local name so old call sites keep their signature.
from m1_ingest.schema_map import _subfield_id as _subfield_id_from_work  # noqa: F401  (single source of truth)

# 32-bucket log histogram: the bucket count is fixed at 32 (pinned by the schema cit_hist_32; bounded, ~23MB).
N_CIT_BUCKETS = 32

# --- Restated values (reading the literals from redlines.yaml anchors them there; they are not opinions invented in code; to change them, edit redlines.yaml) ---
#   require() raises on null; these two keys are set (subfield / mean) -> real values are returned.
#   field_level=subfield; expected_method=mean (the 32-bucket quantile method is discarded; cit_hist_32 is diagnostic only).
FWCI_FIELD_LEVEL: str = require("fwci", "field_level")        # "subfield"
FWCI_EXPECTED_METHOD: str = require("fwci", "expected_method")  # "mean"


def require_snapshot_year() -> Any:
    """Read fwci.snapshot_year (placeholder in redlines.yaml). Unset (null) -> RedlineUnsigned (never a silent default).

    This accumulator does not call it (population counts are window-independent); the guard is here so that when the downstream FWCI ratio needs the
    citation window, snapshot_year must be set first to get a value, otherwise it fails loudly. Identification rules are set by people, not decided in code.
    """
    return require("fwci", "snapshot_year")


def log_bucket_index(cited_by_count: int) -> int:
    """Put a citation count into the 32-bucket log histogram; returns the bucket index in 0..31.

    Binning = floor(log2(c+1)) capped at 31 (pure integer bit-length arithmetic, no floats -> deterministic and identical across machines):
      - c=0 -> bit_length(1)-1 = 0  (0 citations go to bucket 0)
      - c=1 -> bit_length(2)-1 = 1
      - c=3 -> bit_length(4)-1 = 2;  c=5 -> bit_length(6)-1 = 2
      - monotone non-decreasing: a larger c never gives a smaller bucket.
      - very large values (c+1 >= 2^31, i.e. ~2.1 billion citations) are capped at 31 and do not overflow (real citation counts are nowhere near).

    Raises:
      ValueError - cited_by_count < 0 (a citation count cannot be negative; a negative value is data corruption, so fail loudly rather than silently map it to 0).
    """
    if cited_by_count < 0:
        raise ValueError(
            f"cited_by_count must not be negative (got {cited_by_count}); a negative citation count = corrupt data, refusing to silently set it to 0"
        )
    # (c+1).bit_length()-1 == floor(log2(c+1)); integer arithmetic, no floating-point drift.
    idx = (cited_by_count + 1).bit_length() - 1
    return idx if idx < N_CIT_BUCKETS else N_CIT_BUCKETS - 1


# _subfield_id_from_work: see the re-export at the top (single authoritative implementation = schema_map._subfield_id;
#   takes the digit string at the end of the primary_topic.subfield.id URL, missing/empty -> None; the field is often missing -> counted in dropped_null).


class _Cell:
    """Accumulated state of a single (subfield_id, year, work_type) cell."""

    __slots__ = ("work_count", "citation_sum", "hist")

    def __init__(self) -> None:
        self.work_count: int = 0
        self.citation_sum: int = 0
        # 32-bucket log histogram (int32 counts; written as list<int32> unchanged).
        self.hist: list[int] = [0] * N_CIT_BUCKETS

    def add(self, cited_by_count: int) -> None:
        self.work_count += 1
        self.citation_sum += cited_by_count
        self.hist[log_bucket_index(cited_by_count)] += 1


class FwciPopAccumulator:
    """FWCI denominator-population accumulator: sequential scan of all works -> counts per (subfield_id, year, work_type) cell.

    add() covers ALL scanned works, with no seed / economics-department / whitelist filtering (that belongs to the pass layer);
    this accumulator only accumulates faithfully, which guarantees "global baseline == aggregate over the full works set",
    so leave-star in M5 holds on the same basis.

    Diagnostic counts (no information lost):
      - dropped_null: subfield_id or publication_year missing -> enters no cell, but is counted separately.
      - paratext_count: number of works with is_paratext=True (still accumulated per cell; the symmetric drop is done downstream).
    """

    def __init__(self) -> None:
        self._cells: dict[tuple[str, int, str], _Cell] = {}
        self.dropped_null: int = 0
        self.paratext_count: int = 0

    def add(self, work: dict) -> None:
        """Scan one snapshot works record and accumulate it into its cell (missing subfield/year -> dropped_null).

        The self-built denominator reads only: primary_topic.subfield.id (-> subfield_id) / publication_year (-> year) /
        type (-> work_type) / cited_by_count. The native fwci is not read.
        """
        if work.get("is_paratext"):
            self.paratext_count += 1

        subfield_id = _subfield_id_from_work(work)
        year = work.get("publication_year")
        if subfield_id is None or year is None:
            # Incomplete cell key -> not in the population (a None key would contaminate the group); counted separately as a diagnostic, not silently dropped.
            self.dropped_null += 1
            return

        work_type = work.get("type")
        cited = work.get("cited_by_count") or 0  # Missing/None -> 0 citations (NA->0 applies only in this denominator-count context)

        key = (subfield_id, int(year), work_type)
        cell = self._cells.get(key)
        if cell is None:
            cell = _Cell()
            self._cells[key] = cell
        cell.add(int(cited))

    def to_table(self) -> list[dict[str, Any]]:
        """Produce FWCI_BASELINE_POP 6-key rows sorted by (subfield_id, year, work_type) (deterministic).

        Each row goes through assert_matches_schema(FWCI_BASELINE_POP) before writing (exactly 6 keys, extra or missing keys fail).
        cit_hist_32 = a copy of the cell's 32 buckets (bucket sum == work_count).
        """
        out: list[dict[str, Any]] = []
        # None-safe sorting: work_type can be None, and a bare sorted() would compare None with str -> TypeError.
        # Key = (subfield_id, year, work_type is None, work_type or ""): non-None first, None last; deterministic and unchanged.
        for key in sorted(self._cells, key=lambda k: (k[0], k[1], k[2] is None, "" if k[2] is None else k[2])):
            subfield_id, year, work_type = key
            cell = self._cells[key]
            row = {
                "subfield_id": subfield_id,
                "year": year,
                "work_type": work_type,
                "work_count": cell.work_count,
                "citation_sum": cell.citation_sum,
                "cit_hist_32": list(cell.hist),  # Copy, so outside code cannot change the accumulator's internal state
            }
            assert_matches_schema(row.keys(), FWCI_BASELINE_POP, label="FWCI_BASELINE_POP")
            out.append(row)
        return out

    def __iter__(self) -> Iterator[dict[str, Any]]:
        """Lets run_m1 stream into HashBucketWriter (same order as to_table)."""
        return iter(self.to_table())
