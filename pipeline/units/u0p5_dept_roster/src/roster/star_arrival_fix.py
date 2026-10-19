"""Table B human-review corrections applied (arrival years of 15 stars checked person by person): the roster is changed according to
the evidence.

In plain words: the person-by-person check of 15 people (CV/ORCID/Wayback) caught 6 wrong arrival years and one
part-time eligibility problem (A5018638208); this module applies the corrections to the roster: for 6 people year_start is
changed to the evidence year (human_verified=True, the evidence records "human_verified_web:..."+URL), A5018638208
gets the adjunct flag under the part-time rule (the row is kept + an evidence note, rows are not physically deleted -
history stays traceable; removal at the candidate layer is done by U4 consuming the adjudication file).
The adjudication for A5086095616, "local transfer, not a foreign poach", **does not touch the roster row** (year 1997 stays)
- it belongs to the U4 is_foreign_poach consumer.

Write discipline (following the annotations + finalize precedents and the SSD write rules):
  - adjudications = a dated annotations JSON (with authorized_by + evidence URL), in the same directory as the earlier file;
  - the current canonical file is **untouched**, first backed up byte for byte into _backup_2026-07-10_pre_starfix/
    (only the first copy is written; if the backup exists and the current file has since been changed -> fail
    loudly and hand over to a human);
  - the corrected version goes to a **new version directory** roster_v2026-07-10_starfix/ (write_table_b,
    deterministic); target exists with different content -> fail loudly (never overwrite what is there), a re-run
    with the same content is idempotent.
Hard rule: every adjudication must hit exactly 1 row (author_id+dept_key); 0 or >=2 hits -> ValueError
(fail loudly; a misspelled id / a dirty roster is never silent).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
from typing import Mapping

from roster.table_b import write_table_b

# Names of the new version / backup directories (the U4 reader recognizes this version; this is the single source of truth, do not scatter literals).
VERSION_DIR_NAME = "roster_v2026-07-10_starfix"
BACKUP_DIR_NAME = "_backup_2026-07-10_pre_starfix"
ANNOTATIONS_NAME = "roster_fix_2026-07-10_star_arrival_annotations.json"

_SCHOOL_FILE = {"monash_econ": "dept_roster_panel_monash.parquet",
                "unsw_econ": "dept_roster_panel_unsw.parquet"}


def _one_hit(rows: list[dict], author_id: str, dept_key: str, *, what: str) -> int:
    """(author_id, dept_key) must hit exactly 1 row in rows -> return the index; 0 or >=2 hits -> ValueError."""
    hits = [i for i, r in enumerate(rows)
            if r["author_id"] == author_id and r["dept_key"] == dept_key]
    if len(hits) != 1:
        raise ValueError(
            f"star_arrival_fix/{what}: ({author_id}, {dept_key}) matches {len(hits)} roster rows "
            f"(must be exactly 1) — misspelled id / wrong department / dirty roster, fail-loud, never silent"
        )
    return hits[0]


def apply_star_fixes(roster_rows, *, year_fixes: Mapping[str, dict],
                     adjunct_flags: Mapping[str, dict]) -> dict:
    """Merged roster rows of the two schools + adjudications -> new row list + application report (pure function, original rows unchanged).

    year_fixes: {author_id: {dept_key, year_start, evidence}} -
        the hit row gets year_start=evidence year + human_verified=True + confidence="high" +
        evidence=the given string (human_verified_web:... including the URL); year_end untouched.
    adjunct_flags: {author_id: {dept_key, note}} -
        part-time flag: evidence gets "; <note>" appended (note contains 'adjunct_q3', machine-searchable);
        the row is kept, year_start / human_verified are never touched (a contaminated year never gets the human-verified stamp).
    Returns {"rows": new rows, "report": {"year_fixes_applied": [...], "adjunct_flagged": [...]}}.
    """
    rows = [dict(r) for r in roster_rows]
    applied = []
    for aid in sorted(year_fixes):
        fx = year_fixes[aid]
        i = _one_hit(rows, aid, fx["dept_key"], what="year_fix")
        old = rows[i]["year_start"]
        rows[i]["year_start"] = int(fx["year_start"])
        rows[i]["human_verified"] = True
        rows[i]["confidence"] = "high"
        rows[i]["evidence"] = str(fx["evidence"])
        applied.append({"author_id": aid, "dept_key": fx["dept_key"],
                        "old_year_start": old,
                        "new_year_start": int(fx["year_start"])})

    flagged = []
    for aid in sorted(adjunct_flags):
        fl = adjunct_flags[aid]
        i = _one_hit(rows, aid, fl["dept_key"], what="adjunct_flag")
        note = str(fl["note"])
        if "adjunct_q3" not in note:
            raise ValueError(
                f"star_arrival_fix/adjunct_flag: the note of {aid} lacks the 'adjunct_q3' machine tag "
                "(looked up downstream) — the adjudication file format breaks the contract"
            )
        rows[i]["evidence"] = f"{rows[i]['evidence']}; {note}"
        flagged.append(aid)

    return {"rows": rows,
            "report": {"year_fixes_applied": applied, "adjunct_flagged": flagged}}


def _sha256(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_versioned_roster(fixed_rows, *, version_dir, backup_dir,
                           current_paths: Mapping[str, pathlib.Path]) -> dict:
    """Corrected rows of the two schools -> back up the current files + write the new version directory (never overwrite
    what exists; a same-content re-run is idempotent).

    current_paths: {dept_key: path of the current canonical parquet} (read-only + backup, untouched).
    Steps: ① back the current files up into backup_dir (only the first copy is written; the backup exists and the
    current sha changed -> ValueError, hand over to a human); ② split rows by dept_key, write_table_b deterministically
    into version_dir (target exists: same sha -> skip idempotently, different -> ValueError, never overwrite).
    Returns {"backup_created": bool, "files": {dept: path}, "rows_by_school": {dept: n}}.
    """
    version_dir = pathlib.Path(version_dir)
    backup_dir = pathlib.Path(backup_dir)
    rows = [dict(r) for r in fixed_rows]

    # ① Backup (byte for byte; only the first copy is written)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_created = False
    for dept, cur in sorted(current_paths.items()):
        cur = pathlib.Path(cur)
        bp = backup_dir / cur.name
        if bp.exists():
            if _sha256(bp) != _sha256(cur):
                raise ValueError(
                    f"write_versioned_roster: backup {bp.name} exists, but the current file's sha differs from it "
                    "— the current canonical file changed after the backup; the backup anchor is not silently replaced, check by hand"
                )
        else:
            shutil.copy2(cur, bp)
            backup_created = True

    # ② New version (deterministic write; never overwrite existing different content)
    import tempfile
    files = {}
    rows_by_school = {}
    for dept, fname in _SCHOOL_FILE.items():
        school_rows = [r for r in rows if r["dept_key"] == dept]
        if dept not in current_paths:
            continue                      # This school is not in the scope of this run (when the injected test input is smaller)
        target = version_dir / fname
        rows_by_school[dept] = len(school_rows)
        if target.exists():
            with tempfile.TemporaryDirectory() as td:
                probe = pathlib.Path(td) / fname
                write_table_b(school_rows, probe)
                if _sha256(probe) != _sha256(target):
                    raise ValueError(
                        f"write_versioned_roster: new version slot {target} already holds different content — "
                        "never overwrite an existing file (SSD write rule); use a new version directory name or check by hand"
                    )
            files[dept] = str(target)     # Same content -> idempotent
            continue
        write_table_b(school_rows, target)
        files[dept] = str(target)
    return {"backup_created": backup_created, "files": files,
            "rows_by_school": rows_by_school}


def main_star_fix(*, annotations_path, current_paths: Mapping[str, pathlib.Path],
                  version_dir, backup_dir) -> dict:
    """Thin end-to-end assembly: read the adjudications JSON -> apply_star_fixes -> write_versioned_roster
    -> summary sidecar (written to version_dir).

    Adjudications JSON contract (the annotations format):
      year_start_fixes: {aid: {dept_key, year_start, evidence, url?}} -
          when written to the roster, evidence gets the url appended if there is one and it is not embedded yet (source +
          URL both go into evidence);
      identity_dispositions: {aid: {dept_key, disposition, note}} -
          only disposition=adjunct_q3_not_incumbent gets the part-time flag;
      poach_dispositions: do not touch the roster (they belong to the U4 is_foreign_poach consumer), only counted in the summary.
    """
    annotations_path = pathlib.Path(annotations_path)
    ann = json.loads(annotations_path.read_text(encoding="utf-8"))
    if not ann.get("authorized_by"):
        raise ValueError("main_star_fix: adjudication file lacks authorized_by — nothing is written without an authorization statement")

    year_fixes = {}
    for aid, fx in ann.get("year_start_fixes", {}).items():
        ev = str(fx["evidence"])
        url = fx.get("url")
        if url and url not in ev:
            ev = f"{ev} {url}"
        year_fixes[aid] = {"dept_key": fx["dept_key"],
                           "year_start": fx["year_start"], "evidence": ev}
    adjunct_flags = {
        aid: {"dept_key": d["dept_key"], "note": d.get("note", d["disposition"])}
        for aid, d in ann.get("identity_dispositions", {}).items()
        if d.get("disposition") == "adjunct_q3_not_incumbent"
    }

    import pyarrow.parquet as pq
    roster_rows: list[dict] = []
    for dept, p in sorted(current_paths.items()):
        roster_rows += pq.read_table(str(p)).to_pylist()

    fixed = apply_star_fixes(roster_rows, year_fixes=year_fixes,
                             adjunct_flags=adjunct_flags)
    wres = write_versioned_roster(fixed["rows"], version_dir=version_dir,
                                  backup_dir=backup_dir, current_paths=current_paths)

    summary = {
        "date": ann.get("date"),
        "authorized_by": ann["authorized_by"],
        "annotations_path": str(annotations_path),
        "annotations_sha256": hashlib.sha256(
            annotations_path.read_bytes()).hexdigest(),
        "n_year_fixes": len(fixed["report"]["year_fixes_applied"]),
        "n_adjunct_flagged": len(fixed["report"]["adjunct_flagged"]),
        "n_poach_dispositions_not_touching_roster": len(ann.get("poach_dispositions", {})),
        "year_fixes_applied": fixed["report"]["year_fixes_applied"],
        "adjunct_flagged": fixed["report"]["adjunct_flagged"],
        **wres,
    }
    version_dir = pathlib.Path(version_dir)
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "summary_starfix_2026-07-10.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
