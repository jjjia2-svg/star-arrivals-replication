# -*- coding: utf-8 -*-
"""caliber_2026-08-28/cleaned_works.py — the author-signed per-star work-level cleanups, read from
DATA (`data/cal2026-08-28/calls_2026-08-28.csv`), never hard-coded. Repo-authored.

The table carries three actions, each row citing the dossier that mandates it:

* ``exclude``                — a work adjudicated NOT the star's (is_mine=false). These extend the
                               frozen 385-row `verify/fnfix_work_level_calls.csv` when the ported
                               `72` restake runs: A5091826237 −4, A5017222669 −1, A5062352558's 24th call.
* ``merge_from_A5083852619`` — A5017222669's split-ID works (author-signed merge, 2026-08-10 precedent).
                               NOT restake drops: the restake stock deliberately stays understated
                               (the dossier's verdict rests on it; the merge only raises stock).
                               Consumed by the Task-2 works fetch.
* ``first_pub_anchor``       — the dossier-verified earliest OWN work per candidate. first_pub and
                               aage are COMPUTED from these rows (no hand math): aage at
                               Y = arrival_true − 1 is `Y − anchor_year`. Where the snapshot's own
                               robust_first_pub agrees (A5027778630 1985, A5090916445 1997) the anchor
                               changes nothing; where it does not (A5091826237: snapshot 1988 vs 1983;
                               A5017222669 after the 1992 exclusion) the anchor is the injection the
                               restake needs (dossier corrections H-3 / B-1, binding).
"""
from __future__ import annotations

import csv
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[3]
CALLS_CSV = REPO / "data" / "cal2026-08-28" / "calls_2026-08-28.csv"

#: A5017222669's split ID, the one merge source the author signed (register ruling 3).
MERGE_SOURCE_ID = "A5083852619"


def load_calls(path: pathlib.Path = CALLS_CSV) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"{path} is empty")
    return rows


def exclusions(rows=None) -> set[tuple[str, str]]:
    """{(author_id, work_id)} adjudicated not-the-star's — the new restake drops."""
    rows = load_calls() if rows is None else rows
    return {(r["author_id"], r["work_id"]) for r in rows if r["action"] == "exclude"}


def exclusion_rows_for_72(rows=None) -> list[dict]:
    """The exclusions projected onto the frozen calls schema (author_id,work_id,is_mine,reason),
    ready to append to the frozen 385-row `verify/fnfix_work_level_calls.csv` for a `72` run."""
    rows = load_calls() if rows is None else rows
    return [{"author_id": r["author_id"], "work_id": r["work_id"], "is_mine": "false",
             "reason": f"cal2026-08-28: {r['note']} [{r['dossier']}]"}
            for r in rows if r["action"] == "exclude"]


def merge_works(author_id: str, rows=None) -> list[str]:
    """Work-ids the author signed to merge INTO `author_id` (Task-2 fetch; not restake drops)."""
    rows = load_calls() if rows is None else rows
    return [r["work_id"] for r in rows
            if r["author_id"] == author_id and r["action"].startswith("merge_from_")]


def first_pub(author_id: str, rows=None) -> int | None:
    """The dossier-anchored cleaned first-publication year, or None if no anchor is on file."""
    rows = load_calls() if rows is None else rows
    anchors = [r for r in rows if r["author_id"] == author_id and r["action"] == "first_pub_anchor"]
    if not anchors:
        return None
    if len(anchors) > 1:
        raise ValueError(f"{author_id}: {len(anchors)} first_pub anchors; expected at most one")
    return int(anchors[0]["publication_year"])


def aage(author_id: str, arrival_true, rows=None) -> int | None:
    """Machine-caliber academic age at Y = arrival_true − 1, derived from the anchor (no hand math).
    None when no anchor exists for this candidate."""
    fp = first_pub(author_id, rows)
    if fp is None:
        return None
    return (int(arrival_true) - 1) - fp


def first_pub_overrides(rows=None) -> dict[str, int]:
    """{author_id: cleaned first_pub} for every candidate with an anchor on file — the injection
    handed to the restake layer. Uniform on purpose: where the snapshot already agrees, the
    override is a proven no-op (the equivalence run measures it)."""
    rows = load_calls() if rows is None else rows
    return {r["author_id"]: int(r["publication_year"])
            for r in rows if r["action"] == "first_pub_anchor"}
