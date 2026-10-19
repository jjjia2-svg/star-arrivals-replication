"""UQ Table B finalisation v1: applies the final adjudication to the 377-row draft, including the deferred cases.

In plain words: the 377-row draft becomes the final UQ Table B:
  excluded / not admitted (10 people, by name list) have their rows deleted; checked people get hv=True
  and the evidence URL goes into evidence;
  1 person is kept and tagged with an academic-support post type; 1 person is kept with low confidence; 1 person is kept with two spells
  (2015-17 + 2025-26, gap years left empty). All other rows are kept unchanged with hv=False.
Year-column rule: the "verified year span" of a checked person goes into the evidence note and **the year columns are not changed**
  (they hold snapshot/byline evidence years, red line #3; changing them uniformly is left to the final person-by-person check).
  The one exception is the person kept with two spells (the adjudication itself edits the spells).
Output: a new version directory roster_v2026-07-11_uq/ (written by write_table_b, deterministic); an existing one is never overwritten.
Hard rules: every row deletion/note must hit by name (0 hits -> ValueError); (author|name, dept, evidence) is unique; schema is enforced.
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

VERSION_DIR_NAME = "roster_v2026-07-11_uq"
UQ_FILE = "dept_roster_panel_uq.parquet"


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "")
                if not unicodedata.combining(c))
    s = s.replace("’", "'")
    return re.sub(r"[\s\.]+", " ", s).strip().lower()


def _match_rows(rows, *, name=None, author_id=None):
    """Return the list of row indices matching by author_id (preferred) or normalised name."""
    if author_id:
        hits = [i for i, r in enumerate(rows) if r["author_id"] == author_id]
        if hits:
            return hits
    if name is not None:
        key = _norm(name)
        return [i for i, r in enumerate(rows) if _norm(r["display_name"]) == key]
    return []


def apply_uq_adjudication(draft_rows, adjudication: Mapping) -> dict:
    """Draft rows + final adjudication -> finalised rows (pure function, input rows unchanged) + report.

    adjudication keys: removals (name/author_id/why) / special (name -> action...) /
    verified (name/role/verified_span/url/evidence_note).
    Every entry must hit >= 1 row; 0 hits -> ValueError (a misspelt name/id is never silently ignored).
    """
    rows = [dict(r) for r in draft_rows]

    # -- Row deletion (excluded / not admitted) ----------------------------------------------
    removed_people, removed_rows = [], 0
    for rm in adjudication.get("removals", []):
        hits = _match_rows(rows, name=rm["name"], author_id=rm.get("author_id"))
        if not hits:
            raise ValueError(f"apply_uq_adjudication/removal: {rm['name']} "
                             f"(id={rm.get('author_id')}) matched 0 rows in the draft — misspelled name/id, fail-loud")
        for i in sorted(hits, reverse=True):
            rows.pop(i)
        removed_people.append({"name": rm["name"], "n_rows": len(hits), "why": rm["why"]})
        removed_rows += len(hits)

    # -- Special cases ------------------------------------------------------------------
    special_report = {}
    for name, sp in (adjudication.get("special") or {}).items():
        hits = _match_rows(rows, name=name)
        if not hits:
            raise ValueError(f"apply_uq_adjudication/special: {name} matched 0 rows — fail-loud")
        act = sp["action"]
        if act == "keep_two_segments":
            segs = sorted(tuple(s) for s in sp["segments"])
            if len(hits) != len(segs):
                raise ValueError(f"apply_uq_adjudication/special: {name} has {len(hits)} rows != "
                                 f"{len(segs)} segments — a two-segment edit needs one row per segment, fail-loud")
            # Rows with years map to early spell -> late spell in ascending year_start; rows without years (current official) go last -> late spell
            hits_sorted = sorted(hits, key=lambda i: (rows[i]["year_start"] is None,
                                                      rows[i]["year_start"] or 0))
            for i, (ys, ye) in zip(hits_sorted, segs):
                rows[i]["year_start"], rows[i]["year_end"] = ys, ye
                rows[i]["human_verified"] = True
                rows[i]["confidence"] = sp.get("confidence", "high")
                rows[i]["evidence"] = (f"{rows[i]['evidence']}|hv_web:两段裁决;{sp['note'][:90]}"
                                       f"|src:{sp.get('url')}|批2026-07-11")
        elif act in ("keep_support", "keep_low_confidence"):
            tag = "|job_class=academic_support" if act == "keep_support" else ""
            for i in hits:
                rows[i]["human_verified"] = True
                rows[i]["confidence"] = sp.get("confidence", "high")
                rows[i]["evidence"] = (f"{rows[i]['evidence']}{tag}|hv_web:{sp['note'][:90]}"
                                       f"|src:{sp.get('url')}|批2026-07-11")
        else:
            raise ValueError(f"apply_uq_adjudication/special: unknown action={act!r}")
        special_report[name] = {"action": act, "n_rows": len(hits)}

    # -- Verified notes (year columns untouched) ---------------------------------------------
    n_verified_people = 0
    for v in adjudication.get("verified", []):
        hits = _match_rows(rows, name=v["name"])
        if not hits:
            raise ValueError(f"apply_uq_adjudication/verified: {v['name']} matched 0 rows — "
                             "misspelled name / already deleted, fail-loud")
        span = v.get("verified_span") or "—"
        for i in hits:
            rows[i]["human_verified"] = True
            rows[i]["confidence"] = "high"
            rows[i]["evidence"] = (f"{rows[i]['evidence']}|hv_web:{v.get('role', '?')}"
                                   f";核实年段:{span}"
                                   + (f";{v['evidence_note'][:80]}" if v.get("evidence_note") else "")
                                   + f"|src:{v.get('url')}|批2026-07-11")
        n_verified_people += 1

    # -- Guards ------------------------------------------------------------------------
    for r in rows:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="uq_final_row")
    keys = [((r["author_id"] if r["author_id"] is not None
              else f"__noid__{r['display_name']}"), r["dept_key"], r["evidence"])
            for r in rows]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise RuntimeError(f"apply_uq_adjudication: duplicate (author,dept,evidence): "
                           f"{sorted(map(str, dupes))[:3]}")

    report = {
        "n_draft_rows": len(draft_rows),
        "n_final_rows": len(rows),
        "n_removed_rows": removed_rows,
        "n_removed_people": len(removed_people),
        "removed": removed_people,
        "special": special_report,
        "n_verified_people": n_verified_people,
        "n_hv_true_rows": sum(1 for r in rows if r["human_verified"]),
    }
    return {"rows": rows, "report": report}


def write_versioned_uq(rows, ssd_roster_dir) -> dict:
    """Finalised rows -> roster_v2026-07-11_uq/ (deterministic write). Already present and different -> raise; same content is idempotent."""
    base = pathlib.Path(ssd_roster_dir) / VERSION_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    target = base / UQ_FILE
    if target.exists():
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td) / UQ_FILE
            write_table_b(rows, tmp)
            if (hashlib.sha256(tmp.read_bytes()).hexdigest()
                    != hashlib.sha256(target.read_bytes()).hexdigest()):
                raise RuntimeError(f"write_versioned_uq: {target} already exists with different content — "
                                   "never overwrite, check by hand")
    else:
        write_table_b(rows, target)
    return {"file": str(target), "rows": len(rows),
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def write_sidecar(ssd_roster_dir, payload: dict, name: str) -> str:
    p = pathlib.Path(ssd_roster_dir) / VERSION_DIR_NAME / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                 encoding="utf-8")
    return str(p)
