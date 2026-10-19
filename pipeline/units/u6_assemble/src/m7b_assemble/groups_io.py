"""groups_io: assembly of the GROUPS_ABC incumbent membership table (the definition after G1).

Membership table = treated rows (source = PAIRWISE_DOSE distinct triples, C3) + C rows (never-treated,
#6 plan B, with the 6 control-field columns H6). No A/B/C group column and no same-generation predicate (G1/DROP-2/DROP-3).

PK semantics (B6-GROUPS-DEF, the 6 columns are registered in U0 [28]):
  treated rows: (incumbent, star, event) unique; the two control columns = None.
  C rows:      (incumbent, control_star, matched_treated_event) unique;
             event_id = matched_treated_event_id foreign key (never silently minted).
"""
from __future__ import annotations

from typing import Iterable

from common.schema import GROUPS_ABC, assert_matches_schema


class GroupsConsistencyError(ValueError):
    """Contradiction within a membership row (C row with treated=True / duplicate PK / missing control field)."""


def build_groups_membership(dose_rows: Iterable[dict],
                            c_rows: Iterable[dict]) -> list[dict]:
    """dose distinct triples + CEM C rows -> GROUPS_ABC 6-column rows (schema-checked row by row)."""
    out: list[dict] = []
    seen_t: set = set()
    for d in dose_rows:
        key = (d["incumbent_person_id"], d["star_person_id"], d["event_id"])
        if key in seen_t:
            continue                       # distinct triples (degree dimension already collapsed)
        seen_t.add(key)
        out.append({
            "incumbent_person_id": d["incumbent_person_id"],
            "star_person_id": d["star_person_id"],
            "event_id": d["event_id"],
            "treated": True,
            "control_star_person_id": None,
            "matched_treated_event_id": None,
        })
    seen_c: set = set()
    for c in c_rows:
        if c.get("treated") is not False:
            raise GroupsConsistencyError(
                f"C row: treated must be False, got {c.get('treated')!r} "
                f"(incumbent={c.get('incumbent_person_id')!r})")
        if not c.get("control_star_person_id") \
                or not c.get("matched_treated_event_id"):
            raise GroupsConsistencyError("C row lacks control fields (H6 six-column layout)")
        key = (c["incumbent_person_id"], c["control_star_person_id"],
               c["matched_treated_event_id"])
        if key in seen_c:
            raise GroupsConsistencyError(f"duplicate C row PK: {key!r}")
        seen_c.add(key)
        row = {
            "incumbent_person_id": c["incumbent_person_id"],
            "star_person_id": c["star_person_id"],
            "event_id": c["event_id"],
            "treated": False,
            "control_star_person_id": c["control_star_person_id"],
            "matched_treated_event_id": c["matched_treated_event_id"],
        }
        if row["event_id"] != row["matched_treated_event_id"]:
            raise GroupsConsistencyError(
                "C row event_id must equal the matched_treated_event_id foreign key (no new id is minted)")
        out.append(row)
    for r in out:
        assert_matches_schema(r.keys(), GROUPS_ABC, label="groups_ABC")
    return out
