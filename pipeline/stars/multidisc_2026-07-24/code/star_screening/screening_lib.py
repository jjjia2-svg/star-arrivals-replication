# -*- coding: utf-8 -*-
"""star_screening/screening_lib — chemistry + maths (incl. statistics) star-candidate screening, pure-function layer (Wave1b).

This layer **reuses verbatim** the pure functions of the economics rules and reopens no identification decision. Sources:
  - cohort_bin (cohort binning: the first 2 years each get their own bin, then one bin per 4 years): identity/cohort.py
  - person_citation_stock (raw citation stock, full counting, cut at t−1): m7a_star/citation_stock.py
  - fractional_percentiles / competition_rank / cell_estimable / age_eligible / star_flags:
    m7a_star/pctile_engine.py (naive-rank method)
  - robust_first_pub (drops lone leading old papers, same-name contamination with gap>10): m6_generation/academic_age.py

Fixed thresholds (multiplex_pipeline/contracts/redlines.yaml, rule_version=redlines_v4_signed_2026-07-05):
  star.percentile_primary = 0.01 (top 1%); star.percentile_robustness = [0.01, 0.05]
  star.cell_min_n = {pct_1:100, pct_5:20, floor:30}  →  gate1=max(100,30)=100; gate5=max(20,30)=30
  star.min_academic_age = 2 (age<2 dropped, measurement-reliability gate)
  star.age_bins = milojevic
  academic_age.robust_first_pub_max_gap = 10

★Identification red line: this layer screens only and decides nothing. The event table is finalised manually. Three screening-layer choices (not identification decisions; to be reviewed manually):
  (D1) Candidate subfield = per-person **modal subfield** (consistent with the pool), not forced to the single subfield 2002 as in economics —
       chemistry/maths are multi-subfield fields with no single code to force. See the header of run_screening.py + the report.
  (D2) The top-10% estimation gate has no fixed pct_10 → reuse floor=30 as the estimation gate (p05/p01 use the fixed values).
  (D3) No person_map (the multidisc snapshot has no U2 built) → candidates use bare author_id stocks, persons are not folded (recorded as is).
Pure functions, no IO.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction

# --- Fixed thresholds (copied verbatim from redlines.yaml; changing a value means editing the redlines, never deciding it in code) ----------
PERCENTILE_PRIMARY = 0.01          # top 1%
PERCENTILE_ROBUSTNESS = (0.01, 0.05)
CELL_MIN_N = {"pct_1": 100, "pct_5": 20, "floor": 30}
MIN_ACADEMIC_AGE = 2               # age<2 dropped (seniority gate / measurement reliability)
ROBUST_FIRST_PUB_MAX_GAP = 10      # drop lone leading old papers separated from the later career by >10 years

# top-10% threshold (main specification of the task): no fixed pct_10 → reuse floor as the estimation gate (D2)
P10 = 0.10
P05 = 0.05
P01 = 0.01

# cohort-bin constants (reused verbatim from identity/cohort.py)
_SINGLETON_YEARS = 2               # the first 2 years each get their own bin (age 0, age 1)
_BUCKET_WIDTH = 4                  # then one bin per 4 years


def cohort_bin(age: int) -> str:
    """Cohort binning (reused verbatim from identity/cohort.py): first 2 years separate, then one bin per 4 years.

    age 0 → "0", age 1 → "1"; age>=2 → "lo-hi" 4-year bin (2-5 / 6-9 / 10-13 ...).
    age None / negative → raise (upstream focal<first_pub bug, fail loudly).
    """
    if age is None:
        raise ValueError("cohort_bin: age cannot be None")
    a = int(age)
    if a < 0:
        raise ValueError(f"cohort_bin: age cannot be negative ({a}); upstream bug: focal < first_pub")
    if a < _SINGLETON_YEARS:
        return str(a)
    k = (a - _SINGLETON_YEARS) // _BUCKET_WIDTH
    lo = _SINGLETON_YEARS + k * _BUCKET_WIDTH
    return f"{lo}-{lo + _BUCKET_WIDTH - 1}"


def person_citation_stock(works, *, up_to_year: int) -> int:
    """Raw citation stock = Σ cited_by_count (full counting, cut at up_to_year inclusive); reused verbatim from citation_stock.py.

    works: [{publication_year:int, cited_by_count:int}]. Publication year > up_to_year is not counted.
    Missing publication_year / cited_by_count → raise (missing ≠ 0; bad data fails loudly).
    """
    total = 0
    for w in works:
        year = w["publication_year"]
        if year is None:
            raise ValueError(f"person_citation_stock: publication_year is None: {w!r}")
        if year > up_to_year:
            continue
        cites = w["cited_by_count"]
        if cites is None:
            raise ValueError(f"person_citation_stock: cited_by_count is None (missing != 0): {w!r}")
        total += cites
    return total


def robust_first_pub(years, *, max_leading_gap: int = ROBUST_FIRST_PUB_MAX_GAP):
    """Robust first-publication year (reused verbatim from the m6_generation semantics): the earliest year whose gap to the next publication year is <=gap.

    Drops "lone leading old papers" (separated from the real later career by > gap years = another same-name person wrongly merged by OpenAlex, A5028731684 1950s type).
    years: all publication years of the person (may repeat). Empty → None. A continuous career is unchanged.
    Implementation as in the run_u4 rfp CTE: DISTINCT years ascending, take the first year with (next year − this year <= gap, or this year is the last).
    """
    ys = sorted(set(int(y) for y in years))
    if not ys:
        return None
    for i, y in enumerate(ys):
        nxt = ys[i + 1] if i + 1 < len(ys) else None
        if nxt is None or nxt - y <= max_leading_gap:
            return y
    return ys[-1]  # theoretically unreachable (the last one, nxt=None, always matches); fallback


def competition_rank(values):
    """Within-cell competition rank (naive-rank method, reused verbatim from pctile_engine): rank = 1 + #{strictly higher than me}, ties share a rank.

    values: citation stocks of the people in a cell. Returns {value: rank} (by value). Larger is better.
    """
    counts = Counter(values)
    rank = {}
    above = 0
    for v in sorted(counts, reverse=True):
        rank[v] = 1 + above
        above += counts[v]
    return rank


def fractional_percentiles(values):
    """Citation stocks within a cell → within-cell percentile (naive-rank method, reused verbatim from pctile_engine).

    percentile_i = 1 − rank_i/n ∈ [0, 1−1/n]. Ties share the score. Empty → []; single person → [0.0].
    Independent of input order. The star decision goes through the exact integer arithmetic rank ≤ p·n in star_pass_flags.
    """
    vals = list(values)
    n = len(vals)
    if n == 0:
        return []
    rank = competition_rank(vals)
    return [1.0 - rank[v] / n for v in vals]


def cell_estimable(cell_n: int, p: float, cell_min_n: dict = CELL_MIN_N) -> bool:
    """Is the cell large enough to estimate top-p (reused verbatim from pctile_engine): cell_n >= max(cell_min_n[pct_p], floor).

    p → key: 0.01→pct_1, 0.05→pct_5. Top 10% (0.10) has no fixed pct_10 key → only floor is used (D2, to be reviewed manually).
    """
    floor = cell_min_n["floor"]
    key = f"pct_{int(round(p * 100))}"
    per_p = cell_min_n.get(key)          # pct_10 does not exist → None → only floor is used
    thresh = floor if per_p is None else max(per_p, floor)
    return cell_n >= thresh


def age_eligible(academic_age: int, *, min_academic_age: int = MIN_ACADEMIC_AGE) -> bool:
    """Seniority gate (reused verbatim from pctile_engine): academic_age >= min_academic_age (age<2 dropped)."""
    if academic_age is None:
        raise ValueError("age_eligible: academic_age cannot be None")
    return int(academic_age) >= min_academic_age


def star_pass_flags(rank, cell_n, academic_age, *, ps=(P10, P05, P01),
                    cell_min_n: dict = CELL_MIN_N, min_academic_age: int = MIN_ACADEMIC_AGE):
    """Within-cell rank + cell size + academic age → pass or not per tier (reused verbatim from the three-state semantics of star_flags; the order of the gates is fixed).

    Returns dict {p: True/False/None}. Gate order (fixed):
      1. academic age below the seniority gate → False for every tier (definitely not a star; overrides a thin cell);
      2. the cell for this tier is too thin (cell_n < estimation gate) → None for this tier (cannot be estimated; no forced call);
      3. otherwise = rank ≤ p·cell_n (exact integer arithmetic Fraction(rank,cell_n) <= Fraction(str(p))).
    """
    if not age_eligible(academic_age, min_academic_age=min_academic_age):
        return {p: False for p in ps}
    out = {}
    frac = Fraction(rank, cell_n)
    for p in ps:
        if cell_estimable(cell_n, p, cell_min_n):
            out[p] = frac <= Fraction(str(p))
        else:
            out[p] = None
    return out


def dedup_candidate_arrivals(rows, *, year_lo=2005, year_hi=2023):
    """Silver roster rows → candidate arrival events (pure function, easy to test).

    Rule: a spell with year_start ∈ [year_lo, year_hi] = a candidate arrival;
      several spells of the same person at the same school (author_id, school) → take only the **earliest**.
    rows: [{author_id, school, dept_key, field, year_start, year_end, tier}].
    Returns [{author_id, school, dept_key, field, arrival_year}] (arrival_year = earliest year_start).
    """
    best = {}
    for r in rows:
        ys = r.get("year_start")
        if ys is None or not (year_lo <= ys <= year_hi):
            continue
        key = (r["author_id"], r["school"])
        if key not in best or ys < best[key]["arrival_year"]:
            best[key] = {
                "author_id": r["author_id"], "school": r["school"],
                "dept_key": r["dept_key"], "field": r["field"], "arrival_year": ys,
            }
    return sorted(best.values(), key=lambda d: (d["author_id"], d["school"]))


def first_pub_flag(naive_first_pub, robust_fp, academic_age, *,
                   max_leading_gap=ROBUST_FIRST_PUB_MAX_GAP,
                   implausible_age=55, absurd_early_year=1955):
    """First-publication-year plausibility flag (4: the A5028731684 1950s precedent): anomalies are flagged True (reviewed manually case by case, not dropped automatically).

    True when any of: (1) the robust first-publication year dropped an earlier lone old paper (naive < robust, a same-name contamination signal);
      (2) the academic age is implausibly large (>implausible_age); (3) the robust first-publication year is absurdly early (<absurd_early_year).
    """
    if robust_fp is None:
        return True  # no publication year at all → suspicious, flag for manual review
    if naive_first_pub is not None and naive_first_pub < robust_fp:
        return True
    if academic_age is not None and academic_age > implausible_age:
        return True
    if robust_fp < absurd_early_year:
        return True
    return False
