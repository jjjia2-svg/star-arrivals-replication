"""M5-T3b fallback_reports: three safeguards for the S8-4 subfield -> field fallback.

In plain words: some papers lack a "subfield" label, so the quality score can only fall back one level and use the "field" (marked [inferred]). Such inferred values
may be inaccurate, so three safeguards are provided: (1) write the [inferred] share into the diagnostic report (so it is known),
(2) a hook to "re-run without the [inferred] records" (robustness subsample), (3) a control version that "leaves every [inferred] value blank" (most conservative, never filled with 0). All three are required.

Rule anchor (S8-4): missing subfield -> field-level fallback + [inferred] mark + the three safeguards are mandatory.
Diagnostic layer: no identification thresholds; the [inferred] mark (fwci_inferred_fallback) is produced by M5-T2 fwci_raw.compute_fwci.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable


def inferred_fallback_ratio(diag_rows: Iterable[dict]) -> dict:
    """[inferred] share = number of records using the field fallback / number of records with an fwci.

    Returns {"n_inferred": int, "n_with_fwci": int, "ratio": float}.
    n_with_fwci==0 -> ratio 0.0 (nothing to compute; no division by zero, no NaN).
    """
    rows = list(diag_rows)
    n_with_fwci = sum(1 for r in rows if r.get("fwci") is not None)
    n_inferred = sum(1 for r in rows if r.get("fwci_inferred_fallback"))
    ratio = (n_inferred / n_with_fwci) if n_with_fwci else 0.0
    return {"n_inferred": n_inferred, "n_with_fwci": n_with_fwci, "ratio": ratio}


def write_inferred_report(diag_rows: Iterable[dict], out_dir) -> dict:
    """Safeguard 1: write the [inferred] share to <out_dir>/_reports/fwci_inferred_ratio.csv and return the share dict."""
    stats = inferred_fallback_ratio(diag_rows)
    rpt_dir = Path(out_dir) / "_reports"
    rpt_dir.mkdir(parents=True, exist_ok=True)
    path = rpt_dir / "fwci_inferred_ratio.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["n_inferred", "n_with_fwci", "ratio"])
        w.writerow([stats["n_inferred"], stats["n_with_fwci"], f"{stats['ratio']:.6f}"])
    return stats


def drop_inferred_fallback(diag_rows: Iterable[dict]) -> list[dict]:
    """Safeguard 2, hook "re-run without [inferred]": drop records with fwci_inferred_fallback=True (robustness subsample)."""
    return [r for r in diag_rows if not r.get("fwci_inferred_fallback")]


def blank_inferred_fallback(diag_rows: Iterable[dict]) -> list[dict]:
    """Safeguard 3, control "leave blank": set fwci of [inferred] records to None (most conservative, never filled with 0); other records unchanged."""
    out: list[dict] = []
    for r in diag_rows:
        nr = dict(r)
        if nr.get("fwci_inferred_fallback"):
            nr["fwci"] = None
        out.append(nr)
    return out
