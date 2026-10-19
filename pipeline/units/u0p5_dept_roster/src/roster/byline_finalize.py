"""Historical roster finalization - human-review results + printed_only skeleton -> official Table B.

In plain words: only candidates who were "human-reviewed and approved" (keep/keep_adjust) are promoted into the
official roster - rows that have byline rows in the skeleton get the year correction applied and the
"human-verified" stamp; candidates that are stamp-only but confirmed by official records (the A5086383420 case)
are synthesized as rows with manual evidence. Students / part-timers / EBS / excluded / pending candidates never
enter Table B (their verdicts stay in the review results, they are not lost). Official rows are kept as they are
(the official roster wins). Back up before writing the official file.
"""
from __future__ import annotations

import hashlib
import pathlib
import shutil

from common.schema import DEPT_ROSTER_PANEL, assert_matches_schema
from roster.table_b import write_table_b

_KEEP = {"keep", "keep_adjust"}


def build_final_rows(*, official_rows, skeleton_rows, review_rows, dept_key) -> list[dict]:
    """One school's finalized rows = official rows as they are + human-approved candidate rows.

    - keep/keep_adjust with a skeleton row: year correction (keep the skeleton value if the fix is empty) + hv=True +
      confidence=high.
    - keep/keep_adjust without a skeleton row (stamp-only, confirmed by the official record): synthesized with
      evidence="manual"; a missing year correction -> ValueError (the year of a manual row must come from the human
      review, never filled by guess).
    - Any other verdict / candidates not in the review queue: not entered in Table B.
    """
    skel_by_author = {r["author_id"]: r for r in skeleton_rows
                      if r["dept_key"] == dept_key}
    out = [dict(r) for r in official_rows]

    for rv in review_rows:
        if rv["dept_key"] != dept_key or rv["verdict"] not in _KEEP:
            continue
        ys = int(rv["year_start_fix"]) if str(rv.get("year_start_fix") or "").strip() else None
        ye = int(rv["year_end_fix"]) if str(rv.get("year_end_fix") or "").strip() else None
        base = skel_by_author.get(rv["author_id"])
        if base is not None:
            row = dict(base)
            if ys is not None:
                row["year_start"] = ys
            if ye is not None:
                row["year_end"] = ye
            row["human_verified"] = True
            row["confidence"] = "high"
        else:
            if ys is None or ye is None:
                raise ValueError(
                    f"{rv['author_id']} is not in the printed skeleton and the review gave no year correction — "
                    "a manual row's years must come from a checked official record, never guessed"
                )
            row = {"dept_key": dept_key, "author_id": rv["author_id"],
                   "display_name": rv.get("display_name") or None,
                   "year_start": ys, "year_end": ye,
                   "evidence": "manual", "confidence": "high",
                   "human_verified": True}
        out.append(row)

    for r in out:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="table_b_final")
    # Rows without an id (author_id=None) are told apart by name - the real Monash official roster has 3 different people with no id
    keys = [(r["author_id"] if r["author_id"] is not None else f"__noid__{r['display_name']}",
             r["dept_key"], r["evidence"]) for r in out]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise RuntimeError(f"duplicate (author,dept,evidence): {sorted(map(str, dupes))[:3]}")
    return out


def finalize_school_table_b(final_rows, official_path, *, backup_dir) -> dict:
    """Write the official Table B - first back up the original file (byte for byte), then write_table_b (old u0p5
    write parameters, deterministic).

    A fixed-name backup would, on a second finalization (re-run after a verdict update), overwrite the only
    pre-finalize original with the already-finalized file -> the rollback anchor would be lost. So the fixed-name
    backup is **written only the first time** (the clean original, never overwritten); on later re-runs the current
    (already finalized) file is saved as a secondary backup named by content hash (deterministic = same content,
    same name, idempotent; nothing is dropped silently).
    """
    official_path = pathlib.Path(official_path)
    backup_dir = pathlib.Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / official_path.name
    backup_created = False
    superseded_backup = None
    if official_path.exists():
        if backup_path.exists():
            # A pre-finalize backup already exists -> never overwrite it (protects the only pre-finalize original). The current file is saved as a secondary backup.
            digest = hashlib.sha256(official_path.read_bytes()).hexdigest()[:16]
            secondary = backup_dir / f"{official_path.stem}.superseded-{digest}{official_path.suffix}"
            if not secondary.exists():
                shutil.copy2(official_path, secondary)
            superseded_backup = str(secondary)
        else:
            shutil.copy2(official_path, backup_path)
            backup_created = True
    write_table_b(final_rows, official_path)
    return {"file": str(official_path), "rows": len(final_rows),
            "backup": str(backup_path), "backup_created": backup_created,
            "superseded_backup": superseded_backup}
