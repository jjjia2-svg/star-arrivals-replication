"""Wayback candidate-row assembly — yearly profile-page archive -> table-B-shaped candidate rows (candidate layer; never writes the official table B).

In plain words: "this person had a department profile page in these years" = employment evidence
independent of papers -> one row per person [earliest snapshot year, latest snapshot year],
evidence=wayback_snapshot, confidence=medium, human_verified=False (only manual review promotes it to
authoritative). If matched, attach the author_id; if not, leave None (red test #15: never miss a person
and never invent an id).
"""
from __future__ import annotations

import pathlib

from common.schema import DEPT_ROSTER_PANEL, assert_matches_schema
from roster.byline import _write_det


def build_wayback_candidate_rows(people, name_to_author_id: dict) -> list[dict]:
    rows = []
    for p in people:
        years = sorted(p["years"])
        rows.append({
            "dept_key": p["dept_key"],
            "author_id": name_to_author_id.get(p["display_name"]),
            "display_name": p["display_name"],
            "year_start": years[0], "year_end": years[-1],
            "evidence": "wayback_snapshot", "confidence": "medium",
            "human_verified": False,
        })
    for r in rows:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="wayback_candidates")
    return rows


def write_wayback_candidates(rows, out_dir) -> pathlib.Path:
    out_dir = pathlib.Path(out_dir)
    target = out_dir / "wayback_roster_candidates.parquet"
    _write_det(rows, dict(DEPT_ROSTER_PANEL), target,
               ("dept_key", "author_id", "display_name", "year_start",
                "year_end", "confidence", "human_verified"))  # Total order (review L1)
    return target
