"""pctile_engine: three-dimensional cell percentile engine.

In plain words: put each person in a small circle "same subfield × same academic-age bin ×
same year" and compute each person's citation rank / percentile in the circle. Whether the
circle is big enough to estimate a top-p star is decided by the cell estimation gate; too
thin → NA.

This file holds: cell_estimable (estimation gate) + fractional_percentiles (in-cell
percentile, plain rank method) + age_eligible (seniority gate) + star_flags (three-state
star call, rank ≤ p·N in exact integer arithmetic). fallback_level and the NA > 20% flag
are added later (rules to be pinned one by one).

Red lines:
  - per-p estimation gate = max(cell_min_n[pct_p], cell_min_n.floor): top 1% → max(100,30)=100;
    top 5% → max(20,30)=30. Thresholds are read from the passed cell_min_n
    (=RED['star']['cell_min_n']), never hard-coded; a null value (unset) → raise, never a
    silent default. ⚠️ The design text contradicts itself on "20 or 30 for the top 5%" →
    needs human review.
  - Ranking = the in-circle rank over the self-built "field × academic age × year" three
    dimensions (primary rule), **plain rank method**: competition rank rank = 1 + #{strictly
    higher than me} (ties share a rank), percentile = 1 − rank/N; star call = rank ≤ p·N
    (exact integer arithmetic), and a tied block shares one rank ⇒ enters or leaves the
    top-p together, so there is no "half a star". (It is not the mid-rank method
    (strictly lower + 0.5×ties)/N.) ★ Input value = citation "stock" (raw
    citations accumulated to the year before arrival, t−1; not Σ score×FWCI, not h-index).
    OpenAlex's native is_in_top_1_percent is only a robustness reference, not the primary
    (it lacks the academic-age dimension).
Pure functions, no IO.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction

from common._redlines import RedlineUnsigned


def cell_estimable(cell_n: int, p: float, cell_min_n: dict) -> bool:
    """Whether a cell (small circle) is big enough to estimate the top-p star rank = cell_n >= max(cell_min_n[pct_p], floor).

    Combination rule: the per-p estimation gate is the larger of "the gate of that p tier" and "the degenerate hard floor".
    - p → key mapping: 0.01→pct_1, 0.05→pct_5 (int(round(p*100))). No matching key → raise.
    - cell_min_n[pct_p] or floor is None (unset) → raise RedlineUnsigned (never a silent default).
    """
    pct_key = f"pct_{int(round(p * 100))}"    # 0.01→pct_1, 0.05→pct_5
    if pct_key not in cell_min_n:
        raise ValueError(
            f"cell_estimable: p={p} has no matching cell_min_n key {pct_key!r} — only the fixed levels (pct_1/pct_5) are supported"
        )
    per_p = cell_min_n[pct_key]
    floor = cell_min_n.get("floor")
    if per_p is None or floor is None:
        raise RedlineUnsigned(
            f"cell_estimable: cell_min_n[{pct_key}]={per_p!r} / floor={floor!r} contains an unset (null) value — never substituting a default"
        )
    return cell_n >= max(per_p, floor)


def age_eligible(academic_age: int, *, min_academic_age) -> bool:
    """Whether the academic age (= year − first publication year) reaches the star seniority threshold = academic_age >= min_academic_age.

    Why this gate: the age-normalised rank is statistical noise at ages 0-1 (a circle of new graduates all have ≈0 citations,
    and tiny differences flip the percentile; the m-quotient does not converge at low academic age).
    This is a **measurement-reliability gate**, not "young people do not deserve to be stars": it removes the degenerate age≈0 circle ranks from the star call.
    - min_academic_age is read from the red line star.min_academic_age; None (unset) → raise, never a silent default.
    - Real stars such as Yves Zenou (academic age 24) are far above the threshold and unaffected (the golden test never wrongly drops a real star).
    """
    if min_academic_age is None:
        raise RedlineUnsigned(
            "age_eligible: star.min_academic_age = None (threshold not set) — never substituting a default"
        )
    return academic_age >= min_academic_age


def star_flags(rank, cell_n, academic_age, *, gate1, gate5, min_academic_age, p1, p5):
    """In-cell competition rank + cell size + academic age → (top-1% star?, top-5% star?).

    The star call takes **rank** (in-cell competition rank = 1 + #{strictly higher than me}, ties share a rank), not a floating-point pct.
      star call = rank ≤ p·cell_n, in exact integer arithmetic Fraction(rank, cell_n) ≤ Fraction(str(p)),
      with no floating-point boundary (rank ≤ p·N ⟺ percentile ≥ 1−p; percentile is just a continuous expression of the same information);
      a tied block shares a rank ⇒ the whole group enters or leaves together.
    Three-state composition; the order of the gates is fixed:
      ① academic age below the seniority threshold → both tiers False ("by definition not a star"; judged first, overrides a thin circle's None);
      ② the circle is too thin for that tier (cell_n < that tier's estimation gate) → that tier None (cannot be estimated, no forced call);
      ③ otherwise = rank ≤ p·cell_n.
    **Cutoffs are computed from the configured p, not hard-coded**: the caller passes p1/p5 as
    RED["star"]["percentile_primary"] / max(percentile_robustness) (current values 0.01/0.05),
    so a changed p is followed automatically. gate1/gate5 = per-p estimation gates (=max(cell_min_n[pct_p], floor));
    min_academic_age = the seniority threshold red line (None unset → age_eligible raises).
    """
    elig = age_eligible(academic_age, min_academic_age=min_academic_age)
    if not elig:
        return False, False
    s1 = (Fraction(rank, cell_n) <= Fraction(str(p1))) if cell_n >= gate1 else None
    s5 = (Fraction(rank, cell_n) <= Fraction(str(p5))) if cell_n >= gate5 else None
    return s1, s5


def fractional_percentiles(values: list) -> list[float]:
    """Citation-stock values of the people in a cell → each person's in-cell percentile (self-built three-dimensional rank; plain rank method).

    The rank is the competition rank:
      rank_i = 1 + #{j: v_j > v_i}  (competition rank, ties share a rank)
      percentile_i = 1 − rank_i/n ∈ [0, 1−1/n]
    (It is not the mid-rank method "(strictly lower + 0.5×ties)/n".)
    - Tied people get the same score (shared rank → a group enters or leaves the top-p together, no "half a star").
    - Larger is ahead; the star call goes through star_flags with exact integer arithmetic rank ≤ p·n (⟺ percentile ≥ 1−p).
    - Empty → []; a single person → [0.0] (1−1/1); rank 1 is always 1−1/n.
    Deterministic: independent of input order (aggregated by value). (The function name is a historical leftover; what it computes now is the plain-rank percentile.)
    """
    vals = list(values)
    n = len(vals)
    if n == 0:
        return []
    counts = Counter(vals)
    # Competition rank of each distinct value = 1 + the number of people strictly greater than it (accumulated in descending order).
    rank: dict = {}
    above = 0
    for v in sorted(counts, reverse=True):
        rank[v] = 1 + above
        above += counts[v]
    return [1.0 - rank[v] / n for v in vals]
