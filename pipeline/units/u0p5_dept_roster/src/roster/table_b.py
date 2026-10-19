"""U0.5 step 3: write Table B. Build DEPT_ROSTER_PANEL rows and write a deterministic parquet.

What it does:
  Joins "parsed records (parse.py) + author_id alignment verdicts (align.py)" into 8-column Table B rows
  and writes a deterministic parquet.
  Table B is the single authority on "who is on staff in this department in which years".

Table B schema (DEPT_ROSTER_PANEL, registered in U0 common/schema.py, exactly 8 columns):
  dept_key / author_id / display_name / year_start / year_end / evidence / confidence / human_verified

Field rules:
  - dept_key = "monash_econ" (fixed for this slice).
  - author_id = bare (matched) or None (needs_human; red line #1: never guess). Raw author_id; downstream U2 folds it to person_id.
  - evidence = "official_roster" (snapshot of the current Pure roster).
  - confidence = the align verdict (high/medium); needs_human -> "low".
  - human_verified = False (decided automatically, not checked by a person; True only after stars and first-order colleagues are checked by hand).
  - year_start/year_end = the parsed Pure interval (missing -> None).
    NOTE: the year here is the Pure "active publication years" interval, **not the arrival year** (red line #3:
     arrival comes from the modal-institution method plus manual checks, recorded in the arrival slice; never use Pure years/affiliations.years as arrival).

Determinism (reproducibility): before writing, canonical-sort by PK (None last) + fixed pyarrow write
  parameters (zstd / dictionary off / no statistics), so identical content gives an identical byte-level sha. Follows the U1 _writer_util convention.

Hard rules: schema is checked verbatim (assert_matches_schema; extra or missing keys raise); author_id is bare;
  pure data shape + single-file deterministic write, no network.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, Sequence

from common.schema import DEPT_ROSTER_PANEL, assert_matches_schema

DEPT_KEY = "monash_econ"
UNSW_DEPT_KEY = "unsw_econ"             # UNSW slice dept_key (Table A unsw_econ rows)
EVIDENCE_OFFICIAL_ROSTER = "official_roster"

# Deterministic pyarrow write parameters (same as U1 _writer_util._DETERMINISTIC_PARQUET_KW).
_DETERMINISTIC_PARQUET_KW: dict = {
    "compression": "zstd",
    "use_dictionary": False,
    "write_statistics": False,
}


def to_table_b_row(parsed: dict, verdict: dict, *, dept_key: str = DEPT_KEY) -> dict:
    """(Parsed record + align verdict) -> DEPT_ROSTER_PANEL 8-column row.

    Arguments:
      parsed  - output of parse.parse_one / parse_one_unsw (includes display_name/year_start/year_end/...).
      verdict - verdict from align.classify_match / search_author
                (includes author_id: bare|None, confidence: high/medium|None, needs_human: bool).
      dept_key - which department the row goes to (default monash_econ; the UNSW slice passes "unsw_econ"). The default stays Monash for backward compatibility.

    Stored confidence:
      - needs_human=True -> "low" (author_id is also None).
      - otherwise the verdict's confidence (high/medium).

    year_start/year_end pass straight through from parsed (missing -> None; the UNSW page has no years -> always None, red line #3: never guess).
    """
    needs_human = bool(verdict.get("needs_human"))
    if needs_human:
        author_id: Optional[str] = None
        confidence = "low"
    else:
        author_id = verdict.get("author_id")
        confidence = verdict.get("confidence") or "low"

    return {
        "dept_key": dept_key,
        "author_id": author_id,
        "display_name": parsed["display_name"],
        "year_start": parsed.get("year_start"),
        "year_end": parsed.get("year_end"),
        "evidence": EVIDENCE_OFFICIAL_ROSTER,
        "confidence": confidence,
        "human_verified": False,
    }


def _sort_key(r: dict, pk_cols: Sequence[str]):
    """canonical-sort key: None sorts after non-None in the same column (deterministic)."""
    return tuple((r[c] is None, "" if r[c] is None else r[c]) for c in pk_cols)


def write_table_b(rows: Iterable[dict], target) -> None:
    """Write Table B rows as a deterministic single-file parquet; every row is checked against the DEPT_ROSTER_PANEL schema before writing.

    Steps (as U1 write_rows_parquet):
      1. materialise rows;
      2. assert_matches_schema(..., DEPT_ROSTER_PANEL) row by row (extra or missing keys raise);
      3. canonical-sort by (dept_key, author_id, year_start) (None last);
      4. column order = schema key order (fixed);
      5. write with fixed parameters.
    Empty rows -> still writes a 0-row parquet with the correct column order.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    materialized = [dict(r) for r in rows]
    for r in materialized:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="dept_roster_panel")

    pk_cols = ("dept_key", "author_id", "year_start")
    materialized.sort(key=lambda r: _sort_key(r, pk_cols))

    col_order = list(DEPT_ROSTER_PANEL.keys())
    columns = {c: [r[c] for r in materialized] for c in col_order}
    table = pa.table({c: columns[c] for c in col_order})

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        str(target),
        row_group_size=max(1, table.num_rows),
        **_DETERMINISTIC_PARQUET_KW,
    )
