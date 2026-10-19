"""attrition_gate: attrition diagnostic.

Output (pure diagnostics: record and surface, no HALT):
  - departure rate of the two groups (treated vs never-treated control; for the two universities the control pool is empty -> record empty)
  - timing distribution (departure year − arrival year)
  - count of the complete-exit proxy (no publication at all after leaving the department: the observable side of "leaving academia" in the R7 context)
  - lee_bounds_required flag (same kind of mechanism as na_robustness_required;
    this stage only records the flag and does not compute the bounds, since Lee bounds are analysis-layer robustness). The trigger threshold is not set yet, so the
    current semantics = "True if any attrition occurs within the window" + a note saying the threshold is unset and to be set at the 11-university stage
    (an FGM-style observable-prediction test and the Ghanem sharp version also belong to the analysis layer and are not run at this stage).
"""
from __future__ import annotations

from typing import Callable


def run_attrition_diag(treated_pairs: list, *, membership_end: Callable,
                       last_pub_year: Callable, window_years: int,
                       control_pairs=()) -> dict:
    """treated_pairs: [{incumbent_person_id, event_id, arrival_year}] de-duplicated pairs."""

    def _group_stats(pairs) -> dict:
        seen = set()
        n = n_left = n_exit = 0
        timing: dict = {}
        for p in pairs:
            key = (p["incumbent_person_id"], p["event_id"])
            if key in seen:
                continue
            seen.add(key)
            n += 1
            arrival = int(p["arrival_year"])
            end = membership_end(p["incumbent_person_id"])
            if end is not None and arrival <= int(end) <= arrival + window_years:
                n_left += 1
                rel = str(int(end) - arrival)
                timing[rel] = timing.get(rel, 0) + 1
                last = last_pub_year(p["incumbent_person_id"])
                if last is None or int(last) <= int(end):
                    n_exit += 1        # No publication after leaving = complete-exit proxy
        return {
            "n_incumbent_events": n,
            "n_left_dept_within_window": n_left,
            "leave_rate": (n_left / n) if n else None,
            "leave_timing_rel_arrival": dict(sorted(timing.items())),
            "n_exit_academia_proxy": n_exit,
        }

    treated = _group_stats(treated_pairs)
    control = (_group_stats(control_pairs) if control_pairs
               else {"empty": True,
                     "note": "nt 池两校为空 (挂账 §四) — 11 校扩展后补两组对比"})
    any_attrition = (treated["n_left_dept_within_window"] or 0) > 0
    return {
        "gate": "G-attrition",
        "verdict": "WARN" if any_attrition else "PASS",
        "treated": treated,
        "control": control,
        "lee_bounds_required": bool(any_attrition),
        "lee_bounds_note": ("旗=窗内存在流失 (触发阈值 unsigned, 11 校前待人工复核); "
                            "只记旗不算界 — Lee bounds/FGM/Ghanem 属分析层"),
    }
