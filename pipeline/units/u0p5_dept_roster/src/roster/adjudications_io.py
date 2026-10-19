"""Loading of discipline-adjudication files + a scaffold for the two anchor universities (GAP-4).

In plain words: the discipline-boundary adjudication covers only the expansion universities
(registry_v3_adjudications_2026-07-12.json
keys = {uwa, melbourne, anu, deakin, macquarie, sydney, adelaide, uts}) -
**Monash/UNSW are not in it** (root cause D, GAP-4: the star sets of the two anchor universities were frozen earlier and the adjudication systematically missed them).
This module makes "extend the discipline adjudication to the two anchor universities" **mechanically ready**:
  1. build_anchor_adjudication_scaffold() - the entry structure for the two anchor universities (empty removals/verified +
     PENDING_AUTHOR_SIGNATURE); names are filled in only after a human approves them;
  2. load_adjudications(*paths) - load and merge several adjudication files (a key clash -> fail loudly; entry shapes are validated);
  3. assert_adjudication_coverage(adj) - coverage check: all 10 dept_keys (8 expansion universities + 2 anchor universities)
     must have an adjudication entry; a missing one -> ValueError naming GAP-4 (no more silent omission of a university).

Rule (no self-decided identification): the scaffold's removals/verified are **always empty** - who is removed or kept is a human decision;
an empty adjudication passed through registry_v3.apply_adjudication lets everything through (zero behaviour), so the structure is ready without changing the roster.

Exemption: uq_econ needs no adjudication entry - the UQ table B takes the separate uq_finalize track (promoted after a whole-batch human review),
and never passes through this adjudication JSON.
"""
from __future__ import annotations

import json
import pathlib
from typing import Mapping

# the two anchor universities: adjudication JSON key -> dept_key (same style as the adj keys of registry_v3.EXPANSION_SCHOOLS)
ANCHOR_SCHOOLS: dict[str, str] = {"monash": "monash_econ", "unsw": "unsw_econ"}

# UQ is exempt (separate uq_finalize track; does not use the adjudication JSON)
UQ_SEPARATE_LINE: frozenset[str] = frozenset({"uq_econ"})

# required coverage = 8 expansion universities + 2 anchor universities = 10 dept_keys (11 universities - the separate UQ track)
ADJ_REQUIRED_DEPT_KEYS: frozenset[str] = frozenset({
    "melbourne_econ", "sydney_econ", "anu_econ", "uwa_econ", "adelaide_econ",
    "deakin_econ", "uts_econ", "macquarie_econ",
    "monash_econ", "unsw_econ",
})

PENDING_STATUS = "PENDING_AUTHOR_SIGNATURE"

_ANCHOR_NOTE = (
    "unsigned — GAP-4 回补: 07-12 学科边界裁决 (an internal record, not shipped) "
    "只落 9 扩校, 两锚校因星集更早冻结 (star_set_v3 07-11) 被系统性遗漏。"
    "本条目 = 结构脚手架: removals/verified 恒空, 人名 (剔非经济/精算跨校口径统一/"
    "名义挂靠 等) 经人工复核 07-14 根因 A/C/D 证据表后签字填入; 签前空裁决 = 零行为直通。"
)


def build_anchor_adjudication_scaffold() -> dict:
    """Scaffold entries for the two anchor universities (empty removals/verified + PENDING; names always empty)."""
    return {
        key: {
            "dept_key": dept_key,
            "removals": [],
            "verified": [],
            "status": PENDING_STATUS,
            "note": _ANCHOR_NOTE,
        }
        for key, dept_key in ANCHOR_SCHOOLS.items()
    }


def _validate_entry(key: str, entry: Mapping) -> None:
    """Shape check of a single adjudication entry (fail loudly): dept_key/removals/verified must be present;
    each removals/verified item must have a name (a misspelt structure is never silent)."""
    if not isinstance(entry, Mapping):
        raise ValueError(f"load_adjudications[{key}]: entry is not a dict — fail-loud")
    for field in ("dept_key", "removals", "verified"):
        if field not in entry:
            raise ValueError(f"load_adjudications[{key}]: missing field {field!r} — "
                             "adjudication structure is broken, fail-loud")
    for kind in ("removals", "verified"):
        items = entry[kind]
        if not isinstance(items, list):
            raise ValueError(f"load_adjudications[{key}].{kind}: must be a list — fail-loud")
        for it in items:
            if not isinstance(it, Mapping) or "name" not in it:
                raise ValueError(f"load_adjudications[{key}].{kind}: entry is missing name "
                                 f"({it!r}) — fail-loud")


def load_adjudications(*paths) -> dict:
    """Read >= 1 adjudication JSON files and merge them into {key: entry} (the loading path formally "recognises" the anchor-university file).

    Guards: the same key in two files -> ValueError (conflicting adjudication sources, a human must look);
    each entry passes the _validate_entry shape check.
    """
    merged: dict = {}
    for p in paths:
        p = pathlib.Path(p)
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"load_adjudications: {p} top level is not a dict — fail-loud")
        for key, entry in data.items():
            if key in merged:
                raise ValueError(f"load_adjudications: key {key!r} appears in more than one "
                                 f"adjudication file (the later one {p}) — adjudication sources conflict, a person must check, fail-loud")
            _validate_entry(key, entry)
            merged[key] = entry
    return merged


def assert_adjudication_coverage(adj_by_key: Mapping) -> dict:
    """Coverage check: every dept_key in ADJ_REQUIRED_DEPT_KEYS (10 universities) must have an adjudication entry.

    A missing one -> ValueError naming GAP-4 (the earlier case of "the two anchor universities silently absent" is now blocked mechanically).
    Returns the report {covered, pending_signature} - pending = the dept_keys with status=PENDING
    (structure ready, names not yet approved), to print before registry v4 is assembled.
    """
    covered_keys = {e["dept_key"] for e in adj_by_key.values()}
    missing = sorted(ADJ_REQUIRED_DEPT_KEYS - covered_keys)
    if missing:
        raise ValueError(
            "assert_adjudication_coverage: the discipline adjudications are missing a school (GAP-4 scope mismatch): "
            f"{missing} have no adjudication entries — this check mechanically blocks anchor schools from silently going missing; "
            "add the entries (you can first use the empty structure from build_anchor_adjudication_scaffold) and then proceed.")
    pending = sorted(e["dept_key"] for e in adj_by_key.values()
                     if e.get("status") == PENDING_STATUS)
    return {"covered": sorted(ADJ_REQUIRED_DEPT_KEYS), "pending_signature": pending}
