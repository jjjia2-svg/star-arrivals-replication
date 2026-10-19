"""Roster v3 centre backfill merge.

In plain words: the boundary rule (economics institutes and centres in the same establishment/community as the
economics department count in the employed pool) is applied retroactively to Monash/UNSW - 114 recommended additions
+ 3 held-back persons accepted + 6 people missing from the department proper added to the roster.
Centre members enter the employed pool of the main analysis, and the affil_type {centre_only/both} label is
written **machine-readably** into the evidence string (the 8-column schema is untouched, no downstream impact; a
dept-only robustness variant can be cut at any time).

Write discipline (following the star_arrival_fix precedent): v2 (roster_v2026-07-10_starfix) is untouched;
the merged version goes to a **new version directory** roster_v2026-07-11_centres/ (write_table_b, deterministic);
if the target exists with different content -> fail loudly (never overwrite), a re-run with the same content is
idempotent.
Hard rules: v2 rows pass through field by field unchanged; the six human-reviewed year-correction rows must still be
there as they were (guard); an addition must never collide with a v2 author_id or a normalized display_name (a
collision = not a missed person / two ids of the same person suspected -> check by hand);
hv is always False (the year ranges have not passed the final per-person check); author_id is never filled by guess.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import unicodedata
from typing import Mapping

from common.schema import DEPT_ROSTER_PANEL, assert_matches_schema
from roster.table_b import write_table_b

VERSION_DIR_NAME = "roster_v2026-07-11_centres"

_SCHOOL_FILE = {"monash_econ": "dept_roster_panel_monash.parquet",
                "unsw_econ": "dept_roster_panel_unsw.parquet"}


def _norm_name(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "")
                if not unicodedata.combining(c))
    return re.sub(r"[\s\.]+", " ", s).strip().lower()


def _centre_short(centre: str) -> str:
    """Centre description string -> short label (take the first phrase, keep only letters/digits/slashes, at most 24 characters)."""
    head = re.split(r"[（(,，;；ᅳ—:：]", centre or "")[0].strip()
    return (head or "centre")[:24]


def build_centre_addition_rows(additions) -> list[dict]:
    """Addition record (an element of "additions" in the consolidated JSON) -> Table B 8-column rows, one row per segment.

    evidence format (machine-readable):
      centre row:      "centre_roster:<short label>|affil_type=<x>|seg:<i>/<n>|<year-span tag>:<raw≤60>|src:<url>|<batch tag>2026-07-11"
      dept_red_dot row: "dept_history_web:<short label>|affil_type=both|seg:.../src:.../<batch tag>2026-07-11"
      (<year-span tag> and <batch tag> stand for fixed Chinese labels, "year span" and "batch", written by the code.)
    hv=False (has not passed the final per-person check); a missing author_id / year-span edge -> None as it is
    (never filled by guess).
    """
    rows: list[dict] = []
    for a in additions:
        segs = a["segments"]
        n = len(segs)
        prefix = ("dept_history_web:" if a.get("dept_red_dot") else "centre_roster:")
        url = (a.get("evidence_urls") or [None])[0]
        raw_span = str(a.get("years_text_raw") or "")[:60]
        for i, (ys, ye) in enumerate([tuple(s) for s in segs], start=1):
            ev = (f"{prefix}{_centre_short(a['centre'])}"
                  f"|affil_type={a['affil_type']}"
                  + (f"|seg:{i}/{n}" if n > 1 else "")
                  + f"|年段:{raw_span}"
                  + (f"|ruling:{a['ruling'][:80]}" if a.get("ruling") else "")
                  + f"|src:{url}|批2026-07-11")
            rows.append({
                "dept_key": a["dept_key"],
                "author_id": a.get("author_id"),
                "display_name": a["display_name"],
                "year_start": ys,
                "year_end": ye,
                "evidence": ev,
                "confidence": a.get("confidence") or ("medium" if a.get("author_id") else "low"),
                "human_verified": False,
            })
    return rows


def merge_v3(v2_rows_by_school: Mapping[str, list], addition_rows,
             *, year_fixes: Mapping[str, dict]) -> dict:
    """v2 rows of the two schools + addition rows -> v3 rows (pure function, original v2 rows unchanged) + report.

    Guards (all fail loudly):
      ① v2 rows pass through field by field unchanged (placed first, order untouched);
      ② guard for the human-reviewed year-correction rows: every (aid, dept) in year_fixes must have
         year_start == the corrected year and hv=True in v2 (same criterion as adjudications.verify);
      ③ an addition author_id colliding with v2 -> ValueError (already in the department roster = not a missed person);
      ④ an addition normalized display_name colliding with v2 -> ValueError (two ids of the same person suspected,
         check by hand);
      ⑤ (author_id|name, dept, evidence) globally unique (same as the table_b finalization key);
      ⑥ every row is checked against the DEPT_ROSTER_PANEL schema.
    """
    # ② guard: the correction rows are still there unchanged
    by_key = {}
    for school, rows in v2_rows_by_school.items():
        for r in rows:
            if r.get("author_id") is not None:
                by_key[(r["author_id"], r["dept_key"])] = r
    bad = []
    for aid, fx in sorted(year_fixes.items()):
        r = by_key.get((aid, fx["dept_key"]))
        if r is None:
            bad.append(f"{aid}: v2 无该行 ({fx['dept_key']})")
        elif r.get("year_start") != fx["year_start"] or r.get("human_verified") is not True:
            bad.append(f"{aid}: v2 year_start={r.get('year_start')} hv={r.get('human_verified')}"
                       f" ≠ 修正 {fx['year_start']} (hv=True)")
    if bad:
        raise ValueError("merge_v3: the manually verified year-correction rows were altered or are missing — wrong version referenced, fail-loud: "
                         + "; ".join(bad))

    v2_ids = {k[0] for k in by_key}
    v2_names = {_norm_name(r["display_name"])
                for rows in v2_rows_by_school.values() for r in rows}

    # ③④ id / name collision
    clash_id = sorted({r["author_id"] for r in addition_rows
                       if r["author_id"] is not None and r["author_id"] in v2_ids})
    if clash_id:
        raise ValueError(f"merge_v3: added author_id already in the v2 roster {clash_id} — "
                         "a repeated addition, not a missed person; check by hand, stop")
    clash_nm = sorted({r["display_name"] for r in addition_rows
                       if _norm_name(r["display_name"]) in v2_names})
    if clash_nm:
        raise ValueError(f"merge_v3: added display_name clashes with an existing v2 name {clash_nm} — "
                         "possibly one person with two ids, a person must check, fail-loud")

    out_by_school = {s: [dict(r) for r in rows] for s, rows in v2_rows_by_school.items()}
    n_added = {s: 0 for s in out_by_school}
    for r in addition_rows:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="centre_backfill_row")
        school = r["dept_key"]
        if school not in out_by_school:
            raise ValueError(f"merge_v3: added row dept_key={school} is not in the v2 school set "
                             f"{sorted(out_by_school)} — misspelled department, fail-loud")
        out_by_school[school].append(dict(r))
        n_added[school] += 1

    # ⑤ unique key (same as the byline_finalize finalization key)
    keys = [((r["author_id"] if r["author_id"] is not None
              else f"__noid__{r['display_name']}"), r["dept_key"], r["evidence"])
            for rows in out_by_school.values() for r in rows]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise RuntimeError(f"merge_v3: duplicate (author,dept,evidence): {sorted(map(str, dupes))[:3]}")

    for rows in out_by_school.values():
        for r in rows:
            assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="v3_row")

    report = {
        "n_v2": {s: len(v) for s, v in v2_rows_by_school.items()},
        "n_added": n_added,
        "n_v3": {s: len(v) for s, v in out_by_school.items()},
        "n_added_null_author_id": sum(1 for r in addition_rows if r["author_id"] is None),
        "year_fixes_verified": sorted(year_fixes),
    }
    return {"rows_by_school": out_by_school, "report": report}


def write_versioned_v3(rows_by_school: Mapping[str, list], ssd_roster_dir) -> dict:
    """v3 rows of the two schools -> new version directory (deterministic write). Exists with different content -> fail; same content is idempotent."""
    base = pathlib.Path(ssd_roster_dir) / VERSION_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    out = {}
    for school, fname in _SCHOOL_FILE.items():
        rows = rows_by_school.get(school)
        if rows is None:
            raise ValueError(f"write_versioned_v3: missing row for {school}")
        target = base / fname
        if target.exists():
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                tmp = pathlib.Path(td) / fname
                write_table_b(rows, tmp)
                new_b, old_b = tmp.read_bytes(), target.read_bytes()
            if hashlib.sha256(new_b).hexdigest() != hashlib.sha256(old_b).hexdigest():
                raise RuntimeError(f"write_versioned_v3: {target} already exists with different content — "
                                   "never overwrite an existing version directory, a person must check")
        else:
            write_table_b(rows, target)
        out[school] = {"file": str(target), "rows": len(rows),
                       "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    return out


def write_sidecar(base_dir, payload: dict, name: str) -> str:
    """Adjudication/member sidecar JSON goes in the same directory (audit trail)."""
    p = pathlib.Path(base_dir) / VERSION_DIR_NAME / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                 encoding="utf-8")
    return str(p)
