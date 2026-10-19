"""A10 - freeze_star_set writes provenance + a content fingerprint (stars_set_hash).

In plain words: when the star set is frozen, besides star_set.parquet it must (1) compute a deterministic
content fingerprint (stars_set_hash, unchanged by row order) and (2) write a provenance sidecar
(manifest_header.json four-tuple: stars_set_hash / source_snapshot_merkle / config_sha / rule_version). This is
what lets us check "are two runs the same star set" and trace which snapshot and which rule version produced it.

Fingerprint definition: reuse m7a_star.freeze.stars_set_hash({author_id: arrival}), which hashes normalised
content (not raw parquet bytes, so it is stable across pyarrow versions). The bound content is every frozen
candidate's author_id -> arrival year (no "who counts as a star" identification call).

Provenance values (engineering layer, no change to definitions):
  - Provenance is injected, never left empty: source_snapshot_merkle is read from the upstream U1 run_manifest
    (U0 rule: never recompute the merkle); config_sha = sha256_of_red() of the red-line config. If either
    cannot be resolved or is an empty string -> fail-loud; an empty placeholder is never written (the original defect was both values being empty on disk).
  - Accounting for dropped rows with a missing publication_year: build_star_set counts them and the count is
    written to manifest_header as n_dropped_null_pub_year ("dropped silently" became "dropped and counted";
    the dropping itself is unchanged).
"""
import json

import pytest


def _zenou_row():
    """Zenou row that passes the five hard gates of assert_zenou_golden."""
    return {"author_id": "A5017376589", "name": "Yves Zenou", "dept": "monash_econ",
            "arrival": 2016, "subfield": "2002", "age_bin": "22-25", "academic_age": 25,
            "stock": 9000, "percentile": 0.999, "cell_n": 150,
            "is_star_1pct": True, "is_star_5pct": True, "age_eligible": True,
            "is_foreign_poach": True}


def _result(extra=(), n_dropped=0):
    """The result contract adds n_dropped_null_pub_year (counted by build_star_set)."""
    return {"stars": [_zenou_row(), *extra], "no_arrival": [],
            "n_dropped_null_pub_year": n_dropped}


def _fake_derived_root(tmp_path, merkle="snap:TESTMERKLE"):
    """Synthetic derived_root: contains only the U1 real-run reproducibility record run_manifest.json (the source
    that provenance resolution reads)."""
    mdir = tmp_path / "derived" / "u1_edges_full_2026-07-05" / "_manifest"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "run_manifest.json").write_text(
        json.dumps({"source_snapshot_merkle": merkle, "config_sha": "cfg:u1level"}),
        encoding="utf-8")
    return tmp_path / "derived"


def _other(aid, arrival, *, poach=False, s5=True):
    return {"author_id": aid, "name": aid, "dept": "monash_econ", "arrival": arrival,
            "subfield": "2002", "age_bin": "6-9", "academic_age": 8, "stock": 100,
            "percentile": 0.5, "cell_n": 40, "is_star_1pct": False, "is_star_5pct": s5,
            "age_eligible": True, "is_foreign_poach": poach}


# ---- provenance sidecar (four-tuple + content fingerprint) ----------------------------------

def test_freeze_writes_provenance_sidecar(tmp_path):
    """Freezing writes one manifest_header.json: all four-tuple keys present, all values non-empty, plus the fixed rule_version.

    The four-tuple values must all be non-empty (the point of the lineage fingerprint);
    merkle/config_sha are resolved automatically from derived_root and injected.
    """
    from run_u4 import freeze_star_set
    root = _fake_derived_root(tmp_path)
    res = freeze_star_set(_result([_other("A1", 2010, poach=True)]), tmp_path / "out",
                          derived_root=root)
    hpath = tmp_path / "out" / "manifest_header.json"
    assert hpath.exists(), "A10: the provenance sidecar manifest_header.json should be written"
    hdr = json.loads(hpath.read_text(encoding="utf-8"))
    for k in ("stars_set_hash", "source_snapshot_merkle", "config_sha", "rule_version"):
        assert k in hdr, f"provenance is missing 4-tuple key {k}"
        assert hdr[k], f"provenance 4-tuple {k} must not be empty (an empty-string placeholder was the original defect)"
    assert hdr["rule_version"] == "redlines_v4_signed_2026-07-05"
    assert res["stars_set_hash"] == hdr["stars_set_hash"], "the return value should carry the fingerprint written to disk"


def test_freeze_still_writes_parquet(tmp_path):
    """No regression: star_set.parquet is still written, canonical-sorted by author_id.

    freeze now requires injected provenance -> values are passed explicitly.
    """
    import pyarrow.parquet as pq
    from run_u4 import freeze_star_set
    freeze_star_set(_result([_other("A9", 2010), _other("A2", 2011)]), tmp_path,
                    source_snapshot_merkle="M", config_sha="C")
    p = tmp_path / "star_set.parquet"
    assert p.exists()
    aids = pq.read_table(str(p)).column("author_id").to_pylist()
    assert aids == sorted(aids), "rows must be sorted deterministically by author_id"


# ---- fingerprint: deterministic + order-invariant + content-sensitive --------------------------------------
# (freeze requires injected provenance -> the tests below all pass M/C explicitly,
#  and use _result with n_dropped_null_pub_year; the fingerprint assertions themselves are unchanged.)

def _freeze(res_dict, out):
    from run_u4 import freeze_star_set
    return freeze_star_set(res_dict, out, source_snapshot_merkle="M", config_sha="C")


def test_hash_same_input_twice_same(tmp_path):
    """Same input twice -> same hash (deterministic)."""
    a = _freeze(_result([_other("A1", 2010)]), tmp_path / "run1")
    b = _freeze(_result([_other("A1", 2010)]), tmp_path / "run2")
    assert a["stars_set_hash"] == b["stars_set_hash"]


def test_hash_reorder_invariant(tmp_path):
    """Candidates reordered -> same hash (hashes normalised content, not insertion order)."""
    o1, o2, o3 = _other("A1", 2010), _other("A2", 2011), _other("A3", 2012)
    a = _freeze({"stars": [_zenou_row(), o1, o2, o3], "no_arrival": [],
                 "n_dropped_null_pub_year": 0}, tmp_path / "run1")
    b = _freeze({"stars": [o3, o2, _zenou_row(), o1], "no_arrival": [],
                 "n_dropped_null_pub_year": 0}, tmp_path / "run2")
    assert a["stars_set_hash"] == b["stars_set_hash"]


def test_hash_changes_with_arrival(tmp_path):
    """One person's arrival year changes -> hash changes (content-sensitive; it can detect "not the same star set")."""
    a = _freeze(_result([_other("A1", 2010)]), tmp_path / "run1")
    b = _freeze(_result([_other("A1", 2011)]), tmp_path / "run2")
    assert a["stars_set_hash"] != b["stars_set_hash"]


def test_hash_matches_signed_freeze_function(tmp_path):
    """Fingerprint = freeze.stars_set_hash({author_id: arrival}) (no new fingerprint definition is invented)."""
    from m7a_star.freeze import stars_set_hash
    rows = [_zenou_row(), _other("A1", 2010), _other("A2", 2011)]
    res = _freeze({"stars": rows, "no_arrival": [], "n_dropped_null_pub_year": 0}, tmp_path)
    expected = stars_set_hash({r["author_id"]: r["arrival"] for r in rows})
    assert res["stars_set_hash"] == expected


def test_provenance_carries_merkle_and_config(tmp_path):
    """merkle / config_sha are injected by the run_u4 orchestration -> written into provenance."""
    from run_u4 import freeze_star_set
    freeze_star_set(_result([_other("A1", 2010)]), tmp_path,
                    source_snapshot_merkle="MERKLE123", config_sha="CFGSHA456")
    hdr = json.loads((tmp_path / "manifest_header.json").read_text(encoding="utf-8"))
    assert hdr["source_snapshot_merkle"] == "MERKLE123"
    assert hdr["config_sha"] == "CFGSHA456"


def test_freeze_blocks_on_golden_fail_no_write(tmp_path):
    """No regression: if the Zenou golden gate fails -> raise + write nothing to disk (the fingerprint path must not
    bypass the gate).

    provenance / dropped count are deliberately not passed: the golden gate must fire before any
    resolution/accounting (gate first, order unchanged).
    """
    from run_u4 import freeze_star_set, GoldenFailure
    with pytest.raises(GoldenFailure):
        freeze_star_set({"stars": [_other("A1", 2010)], "no_arrival": []}, tmp_path)
    assert not (tmp_path / "star_set.parquet").exists()
    assert not (tmp_path / "manifest_header.json").exists()


# ---- merkle/config_sha injected with real values (empty-string placeholder fixed) ---------

def test_resolve_provenance_reads_u1_manifest_and_config_sha(tmp_path):
    """merkle = read-only from the upstream U1 run_manifest's existing value (U0 rule: never recompute);
    config_sha = sha256_of_red() of the red-line config (same definition as the preflight environment gate 3)."""
    from run_u4 import resolve_provenance
    from common._redlines import sha256_of_red
    root = _fake_derived_root(tmp_path, merkle="snap:ABC123")
    pv = resolve_provenance(root)
    assert pv["source_snapshot_merkle"] == "snap:ABC123"
    assert pv["config_sha"] == sha256_of_red()
    assert pv["config_sha"], "config_sha must be non-empty"


def test_resolve_provenance_fail_loud_when_u1_manifest_missing(tmp_path):
    """Upstream U1 run_manifest.json not on disk -> ValueError (fail-loud, never emit a placeholder string)."""
    from run_u4 import resolve_provenance
    (tmp_path / "derived").mkdir()
    with pytest.raises(ValueError, match="run_manifest"):
        resolve_provenance(tmp_path / "derived")


def test_resolve_provenance_fail_loud_when_merkle_empty(tmp_path):
    """source_snapshot_merkle in the U1 run_manifest is an empty string -> ValueError (an empty value is never passed
    through)."""
    from run_u4 import resolve_provenance
    root = _fake_derived_root(tmp_path, merkle="")
    with pytest.raises(ValueError, match="source_snapshot_merkle"):
        resolve_provenance(root)


def test_freeze_injects_resolved_provenance_exact_values(tmp_path):
    """freeze(derived_root=...) -> the header gets U1's existing merkle + config_sha = sha256_of_red()."""
    from run_u4 import freeze_star_set
    from common._redlines import sha256_of_red
    root = _fake_derived_root(tmp_path, merkle="snap:EXACT")
    freeze_star_set(_result(), tmp_path / "out", derived_root=root)
    hdr = json.loads((tmp_path / "out" / "manifest_header.json").read_text(encoding="utf-8"))
    assert hdr["source_snapshot_merkle"] == "snap:EXACT"
    assert hdr["config_sha"] == sha256_of_red()


def test_freeze_fail_loud_without_any_provenance(tmp_path):
    """Neither explicit injection nor derived_root -> ValueError + nothing written (the old defect was a silent write
    of default empty strings)."""
    from run_u4 import freeze_star_set
    with pytest.raises(ValueError):
        freeze_star_set(_result(), tmp_path)
    assert not (tmp_path / "star_set.parquet").exists()
    assert not (tmp_path / "manifest_header.json").exists()


def test_freeze_rejects_empty_string_provenance(tmp_path):
    """Explicit empty string -> ValueError + nothing written (a placeholder string is never written)."""
    from run_u4 import freeze_star_set
    with pytest.raises(ValueError):
        freeze_star_set(_result(), tmp_path, source_snapshot_merkle="", config_sha="C")
    with pytest.raises(ValueError):
        freeze_star_set(_result(), tmp_path, source_snapshot_merkle="M", config_sha="")
    assert not (tmp_path / "star_set.parquet").exists()
    assert not (tmp_path / "manifest_header.json").exists()


# ---- accounting of dropped rows with a missing publication_year ----------------------

def test_manifest_records_n_dropped_null_pub_year(tmp_path):
    """The dropped count carried in result is written into manifest_header and also returned ("dropped silently"
    became "dropped and counted")."""
    from run_u4 import freeze_star_set
    res = freeze_star_set(_result(n_dropped=18234), tmp_path,
                          source_snapshot_merkle="M", config_sha="C")
    hdr = json.loads((tmp_path / "manifest_header.json").read_text(encoding="utf-8"))
    assert hdr["n_dropped_null_pub_year"] == 18234
    assert res["n_dropped_null_pub_year"] == 18234


def test_freeze_fail_loud_when_dropped_count_missing(tmp_path):
    """result lacks the n_dropped_null_pub_year key -> KeyError (the accounting field must be present; no silent
    missing entry)."""
    from run_u4 import freeze_star_set
    bad = {"stars": [_zenou_row()], "no_arrival": []}   # without n_dropped_null_pub_year
    with pytest.raises(KeyError):
        freeze_star_set(bad, tmp_path, source_snapshot_merkle="M", config_sha="C")


# ---- stock time-basis caveat is written with the frozen files ----------------------

def test_freeze_writes_stock_asof_note(tmp_path):
    """The main definition keeps snapshot stock, with a recorded caveat and a robustness check on a 95-person subset.
    manifest_header must carry stock_asof_note: the snapshot lifetime-citation basis, the magnitude of
    look-ahead inflation (measured as-of/snapshot median 0.36, i.e. inflation ~2.8x), the exactly computable
    subset 95/211, and the path of the measurement output. The main computation is unchanged."""
    from run_u4 import freeze_star_set
    root = _fake_derived_root(tmp_path)
    freeze_star_set(_result(), tmp_path / "out", derived_root=root)
    hdr = json.loads((tmp_path / "out" / "manifest_header.json").read_text(encoding="utf-8"))
    note = hdr["stock_asof_note"]
    assert "快照终身被引" in note["basis"]                  # the basis stated plainly (including post-arrival citations)
    assert "2.8" in note["forward_inflation"]              # measured median magnitude of the inflation
    assert "95/211" in note["asof_subset"]                 # the exactly computable subset is kept for the robustness check
    assert "f_measure_2026-07-16" in note["measurement_artifact"]  # path of the measurement output
    assert "签6" in note["signed"]
