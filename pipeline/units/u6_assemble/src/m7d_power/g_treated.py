"""g_treated: count G_treated, de-duplicated from the single events JOIN star_set (C2/H4).

1% = COUNT(DISTINCT events.dept_id) over events whose star (joined to star_set on author_id) has is_star_1pct;
5% likewise with is_star_5pct.
De-duplication key = events.dept_id (the U4 authority, not the dept_key/inst_id placeholders); counted from the data,
never preset; it takes no per-p file name (regression for the phantom file, T49).
"""
from __future__ import annotations


def count_g_treated(events_rows: list, star_rows: list) -> dict:
    star_by_author = {s["author_id"]: s for s in star_rows}
    out: dict = {}
    for p_level, flag in (("p01", "is_star_1pct"), ("p05", "is_star_5pct")):
        depts = set()
        for e in events_rows:
            s = star_by_author.get(e["star_person_id"])
            if s is not None and bool(s.get(flag)):
                depts.add(e["dept_id"])
        out[p_level] = len(depts)
    return out
