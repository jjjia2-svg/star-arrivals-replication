"""Historical roster step 7 - Table B merge (preview version) + trust set + human-review queue.

In plain words: put the candidate skeleton and the current official roster **into the same preview table** (one row
per piece of evidence, no merging, no conflict), and produce three things: (1) a two-variant preview of Table B
(promoted only after a human settles the stamp rule; the official Table B file is never touched) (2) the trust-set
filter (implements these rules: the official roster wins / candidates need human review / rows without
human review go only into robustness checks) (3) the human-review queue (stars + first-degree collaborators 100%
reviewed + stamp-only pairs, with layered reasons).

Rule discipline: this module adds no new criterion - it only implements the existing rules as mechanical filters;
first-degree collaborator = co-authored with the star at any time in history (deliberately wide: extra human review
does no harm); the queue is a "must-review list", not a verdict.
"""
from __future__ import annotations

import pathlib

from common.schema import DEPT_ROSTER_PANEL, assert_matches_schema
from roster.byline import _write_det

_PREVIEW_STEM = "dept_roster_panel_merged"


def merge_candidate_rows(official_rows, skeleton_rows) -> list[dict]:
    """official_roster rows + candidate skeleton rows -> union with the same schema (one row per distinct evidence,
    no dedup and no merge - human review and downstream steps decide layer by layer on evidence+confidence). Inputs are not modified."""
    merged = [dict(r) for r in official_rows] + [dict(r) for r in skeleton_rows]
    for r in merged:
        assert_matches_schema(r.keys(), DEPT_ROSTER_PANEL, label="dept_roster_panel_merged")
    return merged


def write_merged_preview(merged_rows, out_dir, *, suffix) -> pathlib.Path:
    """Write the preview: dept_roster_panel_merged_<suffix>.parquet - the name contains merged_,
    so it never takes the official Table B file name (a human promotes it once the rule is settled). Deterministic
    write parameters."""
    out_dir = pathlib.Path(out_dir)
    target = out_dir / f"{_PREVIEW_STEM}_{suffix}.parquet"
    # The key includes display_name: several official rows without an id in one department (author_id=None, year=None)
    # tie on the key, so they are ordered by name, and the bytes do not depend on the input row order (determinism must
    # never silently rely on the upstream row order).
    _write_det(merged_rows, dict(DEPT_ROSTER_PANEL), target,
               ("dept_key", "author_id", "evidence", "year_start", "display_name",
                "year_end", "confidence", "human_verified"))
    return target


def trusted_view(merged_rows, *, star_and_first_degree: set) -> list[dict]:
    """Trust set = a mechanical filter implementing the existing rules (no new criteria):
    all official_roster rows enter (the official roster wins); candidate rows need human_verified=True;
    stars + first-degree collaborators follow the same rule as ordinary candidates - never in without human review
    (a machine decision can be vetoed by a human).
    star_and_first_degree is used only to assert the semantics (they have no side door), it does not relax any row."""
    out = []
    for r in merged_rows:
        if r["evidence"] == "official_roster":
            out.append(dict(r))
        elif r["human_verified"] is True:
            out.append(dict(r))
    return out


_REASON_ORDER = {"star_or_first_degree": 0, "stamped_only": 1,
                 "stamped_only_below_threshold": 2}


def build_human_review_queue(merged_rows, *, star_and_first_degree: set,
                             stamped_only_pairs: set,
                             stamped_below_threshold: list | None = None) -> list[dict]:
    """Human-review queue (must-review list, not a verdict):
      P1 star_or_first_degree - not-yet-verified candidate rows of stars + first-degree collaborators (100% reviewed);
      P2 stamped_only - (author, dept) pairs that are stamp-only and pass the threshold (all year evidence is archive
         stamps);
      P3 stamped_only_below_threshold - stamp-only pairs that do NOT pass the threshold (they must also be visible, so the
         coverage is never silently narrowed; no skeleton interval -> year stays empty, nothing is invented).
    If a person has several reasons, the highest priority wins; the queue is ordered P1->P2->P3, stably by (dept, author)
    within a group."""
    q: dict[tuple[str, str], dict] = {}
    for r in merged_rows:
        if r["evidence"] != "raw_affil_year" or r["human_verified"] is True:
            continue
        key = (r["author_id"], r["dept_key"])
        reason = None
        if r["author_id"] in star_and_first_degree:
            reason = "star_or_first_degree"
        elif key in stamped_only_pairs:
            reason = "stamped_only"
        if reason is None:
            continue
        prev = q.get(key)
        if prev is None or _REASON_ORDER[reason] < _REASON_ORDER[prev["reason"]]:
            q[key] = {"priority": _REASON_ORDER[reason],
                      "author_id": r["author_id"], "dept_key": r["dept_key"],
                      "display_name": r["display_name"],
                      "year_start": r["year_start"], "year_end": r["year_end"],
                      "reason": reason}
    for b in (stamped_below_threshold or []):
        key = (b["author_id"], b["dept_key"])
        if key in q:
            continue  # Already queued with a higher-priority reason (e.g. also a first-degree collaborator)
        reason = ("star_or_first_degree" if b["author_id"] in star_and_first_degree
                  else "stamped_only_below_threshold")
        q[key] = {"priority": _REASON_ORDER[reason],
                  "author_id": b["author_id"], "dept_key": b["dept_key"],
                  "display_name": b.get("display_name"),
                  "year_start": None, "year_end": None, "reason": reason}
    rows = sorted(q.values(),
                  key=lambda r: (r["priority"], r["dept_key"], r["author_id"]))
    return rows


def reconcile_counts(official_rows, skeleton_rows) -> dict:
    """Reconciliation of the merge: only on the official site (employed but low output / no papers) / in both sources /
    only in the skeleton (= the pool of recovered leavers).
    Reconciled by (author_id, dept_key); official rows with author_id=None (no id) do not take part in the reconciliation key."""
    off = {(r["author_id"], r["dept_key"]) for r in official_rows if r["author_id"] is not None}
    sk = {(r["author_id"], r["dept_key"]) for r in skeleton_rows if r["author_id"] is not None}
    return {
        "official_only": len(off - sk),
        "both": len(off & sk),
        "skeleton_only": len(sk - off),
        "official_total": len(official_rows),
        "skeleton_total": len(skeleton_rows),
        # Mixed bases (note): total counts rows, only/both count distinct non-None keys - the difference is explicit
        "official_none_id_rows": sum(1 for r in official_rows if r["author_id"] is None),
    }
