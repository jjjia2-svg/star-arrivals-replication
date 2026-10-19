"""M5-T3b fallback_reports — three safeguards for the subfield → field fallback.

In plain words: some papers lack a subfield label, so the quality score can only step up one level and use the
field to estimate it (flagged [inferred]). Such inferred values may be inaccurate, so there are three safeguards:
(1) the [inferred] share goes into the diagnostics report; (2) a hook to rerun without the [inferred] records;
(3) a contrast variant that leaves [inferred] values empty. Red if any of the three is missing.

Rule: a missing subfield → field-level fallback + [inferred] flag + all three safeguards are mandatory.
The [inferred] flag is produced by M5-T2 fwci_raw.compute_fwci (fwci_inferred_fallback). Diagnostics layer, no identification thresholds.
"""


def _diag():
    """Three diagnostic records: W1 normal, W2 [inferred], W3 no fwci."""
    return [
        {"work_id": "W1", "fwci": 2.0, "fwci_inferred_fallback": False},
        {"work_id": "W2", "fwci": 1.5, "fwci_inferred_fallback": True},
        {"work_id": "W3", "fwci": None, "fwci_inferred_fallback": False},
    ]


# ---- Safeguard 1: [inferred] share goes to _reports --------------------------

def test_inferred_ratio_written_to_reports(tmp_path):
    """Of the 2 records with fwci (W1, W2), 1 is inferred → share 0.5, written to _reports/fwci_inferred_ratio.csv."""
    from m5_output.fallback_reports import write_inferred_report
    stats = write_inferred_report(_diag(), tmp_path)
    assert stats == {"n_inferred": 1, "n_with_fwci": 2, "ratio": 0.5}
    p = tmp_path / "_reports" / "fwci_inferred_ratio.csv"
    assert p.exists()
    assert "0.5" in p.read_text()


def test_ratio_empty_no_divzero():
    """No record has fwci → share 0.0; no division by zero, no NaN."""
    from m5_output.fallback_reports import inferred_fallback_ratio
    assert inferred_fallback_ratio([])["ratio"] == 0.0


# ---- Safeguard 2: rerun hook without [inferred] ------------------------------

def test_drop_inferred_fallback_hook():
    """Robustness hook: drop the [inferred] record (W2), keep only those with a true subfield denominator (W1, W3)."""
    from m5_output.fallback_reports import drop_inferred_fallback
    kept = drop_inferred_fallback(_diag())
    assert {r["work_id"] for r in kept} == {"W1", "W3"}


# ---- Safeguard 3: contrast variant with empty values -------------------------

def test_blank_inferred_leaves_na_not_zero():
    """Contrast variant: set fwci of [inferred] records to None (empty), leave the others alone; never fill with 0."""
    from m5_output.fallback_reports import blank_inferred_fallback
    by = {r["work_id"]: r["fwci"] for r in blank_inferred_fallback(_diag())}
    assert by["W2"] is None       # inferred → empty
    assert by["W1"] == 2.0        # non-inferred untouched
    assert by["W2"] != 0          # never filled with 0
