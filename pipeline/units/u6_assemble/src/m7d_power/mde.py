"""mde: descriptive MDE (minimum detectable effect), stratified by generation without collapsing to a binary.

Parameters = the fixed values (RED["power"]): target_power=0.80 / alpha=0.05 /
cluster_unit=department / ICC measured here + the few-clusters inference trio (wild_cluster_bootstrap +
randomization_inference + ferman_pinto). Tampering with RED["power"] to empty -> raise (anti-bypass).

Generation stratification (#15/#7): same generation = |age_gap| <= RED cohort.same_gen_max_gap_years (=5);
age_gap is constant per pair (arrival year frozen #7, guarded by gen_pk_includes_year=False), so the stratification key
naturally does not vary with calendar year; after G1 there is no group column, and stratification uses age_gap+treated.

MDE formula (two-group mean contrast, descriptive):
  MDE = (z_{1-α/2} + z_{power}) × sd_pooled × sqrt(1/n1 + 1/n0) × sqrt(DEFF)
  DEFF = 1 + (m̄ − 1) × ICC (cluster design effect; m̄ = mean rows per cluster)
  ICC measured = one-way ANOVA (between-department variance / total variance); fewer than 2 clusters -> NA.
Report CIs and do not chase significance stars; the MDE is computed only after the data are complete (this stage is the data end point and uses the real frame).
"""
from __future__ import annotations

import math
from typing import Callable

from common._redlines import RED

Z_TWO_SIDED_95 = 1.959963984540054     # z_{1-0.05/2}
Z_POWER_80 = 0.8416212335729143        # z_{0.80}


def signed_power_params() -> dict:
    """Read the fixed values of RED["power"]; empty/missing -> raise (the anti-bypass guard is kept, T44)."""
    power = RED.get("power")
    if not power:
        raise ValueError("RED['power'] is empty — the pinned values were tampered with; refusing to run")
    params = {
        "target_power": float(power["target_power"]),
        "alpha": float(power["alpha"]),
        "cluster_unit": str(power["cluster_unit"]),
        "icc": str(power["icc"]),
        "inference_triple": list(power["inference_triple"]),
    }
    if params["target_power"] != 0.80 or params["alpha"] != 0.05:
        raise ValueError("power parameters differ from the pinned values (0.80/0.05)")
    return params


def generation_strata(rows: list, *, same_gen_max_gap: int | None = None) \
        -> dict:
    """Same-generation / cross-generation stratification (no collapse to a binary = both arms are kept; no group column)."""
    if RED["generation"]["gen_pk_includes_year"] is not False:
        raise ValueError("gen_pk_includes_year must be False (#7: arrival year is frozen)")
    gap_max = (int(RED["cohort"]["same_gen_max_gap_years"])
               if same_gen_max_gap is None else int(same_gen_max_gap))
    strata: dict = {"same_gen": [], "cross_gen": [], "na_age_gap": []}
    for r in rows:
        g = r.get("age_gap")
        if g is None:
            strata["na_age_gap"].append(r)
        elif abs(float(g)) <= gap_max:
            strata["same_gen"].append(r)
        else:
            strata["cross_gen"].append(r)
    return strata


def _mean_sd(vals: list) -> tuple:
    n = len(vals)
    if n < 2:
        return (vals[0] if n else None), None
    mu = sum(vals) / n
    var = sum((v - mu) ** 2 for v in vals) / (n - 1)
    return mu, math.sqrt(var)


def estimate_icc(rows: list, cluster_of: Callable) -> float | None:
    """One-way ANOVA ICC (department clusters). Fewer than 2 clusters / degenerate -> None (reported as NA)."""
    by_c: dict = {}
    for r in rows:
        v = r.get("fwci_frac")
        if v is None:
            continue
        by_c.setdefault(cluster_of(r), []).append(float(v))
    groups = [v for v in by_c.values() if v]
    k = len(groups)
    n = sum(len(g) for g in groups)
    if k < 2 or n <= k:
        return None
    grand = sum(sum(g) for g in groups) / n
    ss_between = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in groups)
    ss_within = sum(sum((v - sum(g) / len(g)) ** 2 for v in g) for g in groups)
    ms_between = ss_between / (k - 1)
    ms_within = ss_within / (n - k) if (n - k) else 0.0
    m_bar = n / k
    denom = ms_between + (m_bar - 1) * ms_within
    if denom <= 0:
        return None
    icc = (ms_between - ms_within) / denom
    return max(0.0, min(1.0, icc))


def _mde_two_group(rows1: list, rows0: list, icc, m_bar) -> dict:
    v1 = [float(r["fwci_frac"]) for r in rows1 if r.get("fwci_frac") is not None]
    v0 = [float(r["fwci_frac"]) for r in rows0 if r.get("fwci_frac") is not None]
    n1, n0 = len(v1), len(v0)
    if n1 < 2 or n0 < 2:
        return {"n1": n1, "n0": n0, "mde": None,
                "note": "组内非空观测 <2, MDE 不可算"}
    _, sd1 = _mean_sd(v1)
    _, sd0 = _mean_sd(v0)
    sd_pool = math.sqrt(((n1 - 1) * sd1 ** 2 + (n0 - 1) * sd0 ** 2)
                        / (n1 + n0 - 2))
    deff = 1.0 + (max(m_bar, 1.0) - 1.0) * (icc or 0.0)
    mde = ((Z_TWO_SIDED_95 + Z_POWER_80) * sd_pool
           * math.sqrt(1.0 / n1 + 1.0 / n0) * math.sqrt(deff))
    return {"n1": n1, "n0": n0, "sd_pooled": sd_pool, "deff": deff,
            "mde": mde}


def compute_mde_report(frame_rows: list, dept_of_event: dict, *,
                       p_label: str) -> tuple:
    """Frame -> (report dict, human-readable txt). Named contrasts: same generation vs cross generation / treated pre vs post
    (the observable side of the not-yet-treated main control = pre-event person-years)."""
    params = signed_power_params()
    strata = generation_strata(frame_rows)

    def _dept(r):
        return dept_of_event.get(r["event_id"], "UNKNOWN_DEPT")

    icc = estimate_icc(frame_rows, _dept)
    clusters = {_dept(r) for r in frame_rows}
    n_nonnull = sum(1 for r in frame_rows if r.get("fwci_frac") is not None)
    m_bar = (n_nonnull / len(clusters)) if clusters else 0.0

    contrasts = {
        "same_gen_vs_cross_gen": _mde_two_group(
            strata["same_gen"], strata["cross_gen"], icc, m_bar),
        "treated_pre_vs_post": _mde_two_group(
            [r for r in frame_rows if r["treated"] and r["post"]],
            [r for r in frame_rows if r["treated"] and not r["post"]],
            icc, m_bar),
    }
    report = {
        "p_label": p_label,
        "params": params,
        "icc_estimate": icc,
        "n_clusters": len(clusters),
        "strata_sizes": {k: len(v) for k, v in strata.items()},
        "contrasts": contrasts,
        "assumptions": [
            "两组均值对比近似 (描述性, 非 dCDH 估计量本身的精确功效)",
            "DEFF = 1+(m̄−1)·ICC; ICC 单因子 ANOVA 自测 (icc=self_estimated)",
            f"簇数 = {len(clusters)} («30) → 少簇三件套推断必做: "
            + ", ".join(params["inference_triple"]),
            "世代键到任年冻结 (#7); 同代=|age_gap|≤"
            + str(RED["cohort"]["same_gen_max_gap_years"]) + " (#15)",
        ],
    }
    lines = [
        f"MDE 功效报告 — {p_label} (U6 m7d)",
        "=" * 46,
        f"已签参数: target_power=0.8 alpha=0.05 "
        f"cluster_unit={params['cluster_unit']} icc={params['icc']}",
        f"推断三件套: {', '.join(params['inference_triple'])}",
        f"ICC 自测 = {icc if icc is not None else 'NA (簇数<2)'}"
        f" | 簇数(系) = {len(clusters)}",
        "",
        "样本结构 (世代分层, 不塌二元):",
        f"  同代 (|age_gap|<=5): {len(strata['same_gen'])} 行",
        f"  跨代 (|age_gap|>5):  {len(strata['cross_gen'])} 行",
        "",
        "具名对比 MDE (headline fwci_frac):",
    ]
    for name, c in contrasts.items():
        label = {"same_gen_vs_cross_gen": "同代 vs 跨代",
                 "treated_pre_vs_post":
                 "treated 事件后 vs 事件前 (not-yet-treated 观测面)"}[name]
        if c.get("mde") is not None:
            lines.append(f"  {label}: MDE={c['mde']:.4f} "
                         f"(n1={c['n1']}, n0={c['n0']}, DEFF={c['deff']:.3f})")
        else:
            lines.append(f"  {label}: NA — {c.get('note', '')}")
    lines += [
        "",
        "假设 (全部可审计):",
        *[f"  - {a}" for a in report["assumptions"]],
        "",
        "声明: 报 CI 不追星号; β_cross 在澳洲小样本功效不足是已知 — 分层 + "
        "wild cluster bootstrap。",
    ]
    return report, "\n".join(lines)
