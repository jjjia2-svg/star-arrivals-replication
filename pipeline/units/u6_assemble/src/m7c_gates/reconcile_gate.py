"""reconcile_gate (G-reconcile + G-reverse): strict tally validation.

(A) tally-reconcile: for each tally assert expected == kept+failed+skipped + balanced
    + a strict key set (exactly the seven TALLY keys; extra or missing keys are both rejected, and diagnostics go to sidecars instead of being mixed into the ledger).
(B) G-reverse: WARNING B6-REVVAL: the whole-file contract of common/reverse_validate.py is missing (B-1),
    so this half is explicitly skipped and registered, and never produces a false green.
"""
from __future__ import annotations

import json
import pathlib

from common.schema import TALLY
from identity.exit_codes import TALLY_IMBALANCE


class TallyImbalance(Exception):
    """Six-key tally is unbalanced / key set is not strict."""

    exit_code: int = TALLY_IMBALANCE


def run_reconcile_gate(tally_paths) -> dict:
    n = 0
    for p in tally_paths:
        doc = json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
        extra = set(doc) - set(TALLY)
        missing = set(TALLY) - set(doc)
        if extra or missing:
            raise TallyImbalance(
                f"{p}: tally key set not strict (extra={sorted(extra)} "
                f"missing={sorted(missing)}) — diagnostic counts go to a sidecar, not into TALLY")
        if doc["expected"] != doc["kept"] + doc["failed"] + doc["skipped"]:
            raise TallyImbalance(
                f"{p}: arithmetic arm does not balance expected={doc['expected']} != "
                f"kept+failed+skipped={doc['kept']+doc['failed']+doc['skipped']}")
        if doc["balanced"] is not True:
            raise TallyImbalance(f"{p}: balanced must be True")
        n += 1
    return {"gate": "G-reconcile", "verdict": "PASS", "n_tallies": n,
            "reverse": reverse_gate_status()}


def reverse_gate_status() -> dict:
    return {"status": "skip",
            "reason": ("B6-REVVAL: common/reverse_validate.py 整文件契约缺失 "
                       "(B-1) — U0 产出前 G-reverse 不实现, 显式登记不产假绿")}
