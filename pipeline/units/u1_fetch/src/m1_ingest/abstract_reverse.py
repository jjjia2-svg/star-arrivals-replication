"""M1-T-ABS abstract_reverse.py - abstract inverted-index reversal + work_text output.

What it does:
  - OpenAlex works store the abstract as abstract_inverted_index = {token: [positions]} (no plain-text abstract);
    this module puts it back together by position into a readable abstract_text.
  - flatten_work_text outputs the 3 WORK_TEXT columns (work_id, title, abstract_text); it does NOT produce has_abstract.
  - write_work_text writes deterministically, with a schema check before writing.

Official usage (OpenAlex works object):
  abstract_inverted_index = {token:[positions]}; reversal = look up the token by position, sort by position and join;
  gaps in positions are skipped (OpenAlex is lossy; observed {"Mutu":[0,19,26], ...} str -> list[int]).
Source: OpenAlex documentation (download-to-your-machine; work object: title/display_name/abstract_inverted_index).

Conventions:
  - The main dose is shared-reference coupling (refs); abstracts are only a secondary-dose robustness check
    -> this table is raw material for the secondary dose, not the main dose.
  - work_text is reversed only for works that enter candidate pairs (pass-B/C seeds + frontier), not for all 492M works (size constraint).

Red line: pure data shape; touches no identification-rule placeholder.
"""
from __future__ import annotations

from typing import Iterable, Optional

from common.schema import WORK_TEXT
from m1_ingest._writer_util import bare, write_rows_parquet

# Size switch: work_text is reversed only for candidate-pair works; run_m1 feeds rows from the pass-B/C hit set. On by default.
ENABLE_WORK_TEXT: bool = True


def reconstruct_abstract(inverted_index) -> Optional[str]:
    """{token:[positions]} inverted index -> readable abstract_text (re-assembled by position).

    - None / empty dict -> None (no abstract);
    - otherwise build pos[position]=token, then join in ascending position order;
    - gap in positions (an index with no token) -> skip it (OpenAlex data is lossy and is kept as is; no padding, no raise);
    - a token at several positions -> filled at each position (repeated occurrences are kept).
    """
    if not inverted_index:
        return None
    pos: dict[int, str] = {}
    for token, plist in inverted_index.items():
        for p in plist:
            pos[p] = token
    if not pos:
        return None
    # Join in ascending order of the positions that actually occur (a gap is not in pos, so it is skipped naturally).
    return " ".join(pos[i] for i in sorted(pos))


def flatten_work_text(work: dict) -> dict:
    """One work -> WORK_TEXT row {work_id(bare), title, abstract_text}.

    - work_id: bare(work["id"]);
    - title: work["title"], falling back to work["display_name"], else None (the row is not dropped);
    - abstract_text: reconstruct_abstract(work["abstract_inverted_index"]) (missing -> None);
    - exactly 3 keys; never produces has_abstract.
    """
    title = work.get("title")
    if title is None:
        title = work.get("display_name")
    return {
        "work_id": bare(work.get("id")),
        "title": title,
        "abstract_text": reconstruct_abstract(work.get("abstract_inverted_index")),
    }


def write_work_text(rows: Iterable[dict], target) -> None:
    """Write the work_text parquet (PK=work_id; deterministic, schema check before writing)."""
    write_rows_parquet(
        rows, target,
        schema=WORK_TEXT,
        pk_cols=("work_id",),
        label="WORK_TEXT",
    )
