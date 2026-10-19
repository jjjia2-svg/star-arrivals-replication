"""Table B v2 - affil_type + year_start_provenance promoted to structured columns.

In plain words:
  affil_type: the centre backfill deliberately wrote affil_type (dept_only/centre_only/both) **only into the evidence
    string** and left the 8-column schema alone - so "filter centre members by field / cut a dept-only robustness
    variant at any time" could not be executed by machine. This module promotes it to a proper
    DEPT_ROSTER_PANEL_V2 column.
  year_start_provenance: 83% of arrival years were not human-verified and their source could not be traced -
    this column is a source sub-label (bio_stated = year stated on a page/CV/ORCID;
    snapshot_first_seen = first seen in a snapshot, left-censored; unknown).

Mechanical backfill discipline (no discretionary identification decisions):
  - only **infer** from the existing evidence strings; if it cannot be inferred -> conservative unknown / dept_only
    (the default for the entry path);
  - never invent a new fact and never change any value of the 8-column base (the year columns stay untouched);
  - the year of official_roster is the Pure "active publication range", not a stated arrival (judged "no basis")
    -> honestly recorded as unknown, not passed off as bio_stated;
  - hv=True **takes no part** in the inference - the hv semantics of the two anchor schools (years checked) differ
    from the hv semantics of the 9 expansion schools (only identity checked, year columns untouched) (the "hv semantics
    blind spot"), and the mechanical layer cannot tell them apart -> look at the evidence string only.

Write discipline (following the centre_backfill / registry_v3 precedent):
  frozen files are read-only; new products go to a new dated directory (the caller gives the path); target exists
  with different content -> fail loudly, a re-run with the same content is idempotent; deterministic write
  (canonical sort + fixed pyarrow write parameters).
"""
from __future__ import annotations

import hashlib
import pathlib
import re
from collections import Counter
from typing import Iterable, Optional, Sequence

from common.schema import DEPT_ROSTER_PANEL, DEPT_ROSTER_PANEL_V2, assert_matches_schema
from roster.table_b import _DETERMINISTIC_PARQUET_KW, to_table_b_row

AFFIL_TYPE_VALUES = ("dept_only", "centre_only", "both")
PROVENANCE_VALUES = ("bio_stated", "snapshot_first_seen", "unknown")

# Machine tag in evidence (format written by the centre backfill: "...|affil_type=<x>|...")
_AFFIL_TAG_RE = re.compile(r"affil_type=([^|]+)")
# Year-span segment of centre/dept_red_dot rows: "|<year-span tag>:<raw>|" (the tag is the fixed Chinese label for "year span"; read up to the next |)
_YEAR_SPAN_RE = re.compile(r"\|年段:([^|]*)")

# Source marker inside the year-span text (searched only within the year-span segment; the hv adjudication note / src URL are not touched - avoids false hits)
_BIO_MARKERS = ("bio：", "bio:")
_SNAPSHOT_MARKERS = ("在列", "快照", "首见", "wayback", "Wayback")


# ═══ Pure functions: mechanical inference ════════════════════════════════════════════════════════
def infer_affil_type(evidence: str) -> str:
    """evidence string -> affil_type.

    Rules:
      - contains the machine tag "affil_type=<x>" -> take x (value outside the domain -> ValueError, fail loudly);
      - no tag -> "dept_only" (the centre backfill is the only entry path that writes the tag;
        every other path = department roster/byline/manual/human-verified web evidence -> entered on the department side).
    """
    m = _AFFIL_TAG_RE.search(evidence or "")
    if m is None:
        return "dept_only"
    val = m.group(1).strip()
    if val not in AFFIL_TYPE_VALUES:
        raise ValueError(f"infer_affil_type: evidence carries unknown affil_type={val!r} "
                         f"(allowed values {AFFIL_TYPE_VALUES}) — evidence string is broken, fail-loud")
    return val


def infer_year_start_provenance(evidence: str, year_start: Optional[int]) -> str:
    """(evidence, year_start) -> source sub-label. Conservative: cannot infer = unknown.

    Priority:
      1. year_start empty -> unknown (no year to trace);
      2. human_verified_web:* human-verified web-evidence strings -> bio_stated (the string itself is the stated source);
      3. centre_roster:/dept_history_web: rows -> look only at the text of the |<year-span tag>:...| segment:
         explicit bio marker > in-snapshot marker (a year taken from an explicit statement has priority); neither -> unknown
         (including years inferred from an "estimated..."/OpenAlex segment - not passed off as stated);
      4. base source = wayback_snapshot -> snapshot_first_seen
         (the `|hv:<boundary-accept tag>` suffix only verifies identity and leaves the year columns untouched -> no flip;
         the tag is a fixed Chinese label);
      5. everything else (the Pure active publication range of official_roster / manual / raw_affil_year /
         arc_grant ...) -> unknown - judged "no basis", the mechanical layer does not pass them off as a source.
    """
    if year_start is None:
        return "unknown"
    ev = evidence or ""
    base = ev.split("|", 1)[0]

    if base.startswith("human_verified_web:"):
        return "bio_stated"

    if base.startswith(("centre_roster:", "dept_history_web:")):
        m = _YEAR_SPAN_RE.search(ev)
        span = m.group(1) if m else ""
        if any(mk in span for mk in _BIO_MARKERS):
            return "bio_stated"
        if any(mk in span for mk in _SNAPSHOT_MARKERS):
            return "snapshot_first_seen"
        return "unknown"

    if base.strip() == "wayback_snapshot":
        return "snapshot_first_seen"

    return "unknown"


def upgrade_row_to_v2(row: dict) -> dict:
    """V1 8-column row -> V2 10-column row (pure function, input row unchanged, the 8 columns pass through field by field)."""
    assert_matches_schema(row.keys(), DEPT_ROSTER_PANEL, label="panel_v2_input")
    out = dict(row)
    out["affil_type"] = infer_affil_type(row["evidence"])
    out["year_start_provenance"] = infer_year_start_provenance(
        row["evidence"], row["year_start"])
    assert_matches_schema(out.keys(), DEPT_ROSTER_PANEL_V2, label="panel_v2_output")
    return out


def to_table_b_row_v2(parsed: dict, verdict: dict, *, dept_key: str,
                      affil_type: str = "dept_only") -> dict:
    """The build path directly produces a V2 row = to_table_b_row (8 columns, untouched) + two new columns.

    affil_type is given explicitly by the build path (the department roster path defaults to dept_only; the centre
    backfill path passes centre_only/both); provenance follows the same inference rule (official_roster range year
    -> unknown).
    """
    if affil_type not in AFFIL_TYPE_VALUES:
        raise ValueError(f"to_table_b_row_v2: affil_type={affil_type!r} is not in the allowed values "
                         f"{AFFIL_TYPE_VALUES}")
    row = to_table_b_row(parsed, verdict, dept_key=dept_key)
    row["affil_type"] = affil_type
    row["year_start_provenance"] = infer_year_start_provenance(
        row["evidence"], row["year_start"])
    assert_matches_schema(row.keys(), DEPT_ROSTER_PANEL_V2, label="table_b_row_v2")
    return row


# ═══ Deterministic write (V2 write_table_b, same sort / same write parameters) ═════════════════════════
def _sort_key(r: dict, pk_cols: Sequence[str]):
    return tuple((r[c] is None, "" if r[c] is None else r[c]) for c in pk_cols)


def write_table_b_v2(rows: Iterable[dict], target) -> None:
    """V2 rows -> one deterministic parquet file (in the style of table_b.write_table_b, schema switched to V2)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    materialized = [dict(r) for r in rows]
    for r in materialized:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL_V2, label="dept_roster_panel_v2")

    pk_cols = ("dept_key", "author_id", "year_start")
    materialized.sort(key=lambda r: _sort_key(r, pk_cols))

    col_order = list(DEPT_ROSTER_PANEL_V2.keys())
    columns = {c: [r[c] for r in materialized] for c in col_order}
    table = pa.table({c: columns[c] for c in col_order})

    target = pathlib.Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(target), row_group_size=max(1, table.num_rows),
                   **_DETERMINISTIC_PARQUET_KW)


# ═══ Backfiller: frozen 8-column parquet → new 10-column parquet ════════════════════════════
def _read_v1_rows(src) -> list[dict]:
    """Read the 8-column panel parquet -> native python rows (same normalization as the registry_v3 read-back)."""
    import pandas as pd

    df = pd.read_parquet(src)
    rows = df.to_dict("records")
    for r in rows:
        for k in ("year_start", "year_end"):
            r[k] = None if pd.isna(r[k]) else int(r[k])
        r["author_id"] = None if pd.isna(r["author_id"]) else str(r["author_id"])
        r["evidence"] = str(r["evidence"])
        r["confidence"] = str(r["confidence"])
        r["display_name"] = str(r["display_name"])
        r["dept_key"] = str(r["dept_key"])
        r["human_verified"] = bool(r["human_verified"])
    return rows


def backfill_panel_v2(src, dst) -> dict:
    """Frozen 8-column panel -> 10-column V2 panel (new file) + report.

    Guards:
      ① src is read-only, untouched;
      ② the 8-column base passes through field by field (guaranteed by the pure function upgrade_row_to_v2);
      ③ the row count is unchanged;
      ④ dst exists with different content -> RuntimeError (never overwrite); a re-run with the same content is idempotent.
    """
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    v1_rows = _read_v1_rows(src)
    v2_rows = [upgrade_row_to_v2(r) for r in v1_rows]
    if len(v2_rows) != len(v1_rows):
        raise RuntimeError("backfill_panel_v2: row count drifted — fail-loud")

    if dst.exists():
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td) / dst.name
            write_table_b_v2(v2_rows, tmp)
            new_b, old_b = tmp.read_bytes(), dst.read_bytes()
        if hashlib.sha256(new_b).hexdigest() != hashlib.sha256(old_b).hexdigest():
            raise RuntimeError(f"backfill_panel_v2: {dst} already exists with different content — "
                               "an existing output is never overwritten; check by hand")
    else:
        write_table_b_v2(v2_rows, dst)

    return {
        "src": str(src),
        "dst": str(dst),
        "n_rows": len(v2_rows),
        "affil_type_counts": dict(Counter(r["affil_type"] for r in v2_rows)),
        "year_start_provenance_counts": dict(
            Counter(r["year_start_provenance"] for r in v2_rows)),
        "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
    }
