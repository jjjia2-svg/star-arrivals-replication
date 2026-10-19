"""Historical roster step 0 pre-gate TDD - HALT-or-go (the implementation layer of red test #16).

Gate semantics:
  - probe_upstream: works_affil/authorship_edges present in full + raw_affiliation_strings is
    list<str>, not flattened -> return the probe record (frozen into the manifest); otherwise SystemExit(EXIT_ROSTER_UPSTREAM_FAIL=25),
    never run blindly on empty tables. SAMPLE-only also counts as absent (red test #16).
  - probe_registry: pass only if the school's entity rows are in Table A + dept_name_variants is non-empty + human_verified=True
    (the pre-gate half of red test #7); otherwise SystemExit(EXIT_ROSTER_REGISTRY_MISSING=26),
    never silently hit 0 with an empty whitelist.
"""
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from roster.table_a import build_table_a_rows, write_table_a


def _write_works_affil(d, *, flatten_raw=False, name="part-00000.parquet"):
    d.mkdir(parents=True, exist_ok=True)
    if flatten_raw:
        raw = pa.array(["Department of Economics, Monash University"], type=pa.string())
    else:
        raw = pa.array([["Department of Economics, Monash University"]], type=pa.list_(pa.string()))
    t = pa.table({
        "work_id": pa.array(["W1"], type=pa.string()),
        "author_id": pa.array(["A1"], type=pa.string()),
        "institution_id": pa.array(["I56590836"], type=pa.string()),
        "raw_affiliation_strings": raw,
    })
    pq.write_table(t, str(d / name))


def _write_edges(d, name="part-00000.parquet"):
    d.mkdir(parents=True, exist_ok=True)
    t = pa.table({
        "work_id": pa.array(["W1"], type=pa.string()),
        "author_id": pa.array(["A1"], type=pa.string()),
        "publication_year": pa.array([2010], type=pa.int16()),
    })
    pq.write_table(t, str(d / name))


def test_probe_upstream_ok_returns_manifest_record(tmp_path):
    from roster.byline import probe_upstream

    wa, ae = tmp_path / "works_affil", tmp_path / "authorship_edges"
    _write_works_affil(wa)
    _write_edges(ae)
    rec = probe_upstream(wa, ae)
    assert rec["works_affil_files"] == 1
    assert rec["authorship_files"] == 1
    assert rec["raw_affil_type"] == "list<string>"
    assert rec["publication_year_type"] == "int16"


def test_probe_upstream_missing_dir_halts(tmp_path):
    from roster.byline import probe_upstream

    ae = tmp_path / "authorship_edges"
    _write_edges(ae)
    with pytest.raises(SystemExit) as e:
        probe_upstream(tmp_path / "no_works_affil", ae)
    assert e.value.code == 25


def test_probe_upstream_sample_only_halts(tmp_path):
    """Only data_SAMPLE.parquet = the full data was not produced -> HALT 25 (red test #16); never pass a sample off as the full data."""
    from roster.byline import probe_upstream

    wa, ae = tmp_path / "works_affil", tmp_path / "authorship_edges"
    _write_works_affil(wa, name="data_SAMPLE.parquet")
    _write_edges(ae)
    with pytest.raises(SystemExit) as e:
        probe_upstream(wa, ae)
    assert e.value.code == 25


def test_probe_upstream_flattened_raw_affil_halts(tmp_path):
    from roster.byline import probe_upstream

    wa, ae = tmp_path / "works_affil", tmp_path / "authorship_edges"
    _write_works_affil(wa, flatten_raw=True)
    _write_edges(ae)
    with pytest.raises(SystemExit) as e:
        probe_upstream(wa, ae)
    assert e.value.code == 25


def _table_a_path(tmp_path, rows=None):
    p = tmp_path / "econ_dept_registry.parquet"
    write_table_a(rows if rows is not None else build_table_a_rows(), p)
    return p


def test_probe_registry_ok(tmp_path):
    from roster.byline import probe_registry

    rec = probe_registry(_table_a_path(tmp_path), ["monash_econ", "unsw_econ"])
    assert set(rec) == {"monash_econ", "unsw_econ"}
    assert rec["monash_econ"]["openalex_inst_id"] == "I56590836"
    assert len(rec["monash_econ"]["dept_name_variants"]) >= 1


def test_probe_registry_missing_school_halts(tmp_path):
    from roster.byline import probe_registry

    with pytest.raises(SystemExit) as e:
        probe_registry(_table_a_path(tmp_path), ["monash_econ", "ghost_econ"])
    assert e.value.code == 26


def test_probe_registry_empty_variants_halts(tmp_path):
    from roster.byline import probe_registry

    rows = build_table_a_rows()
    rows[0] = dict(rows[0], dept_name_variants=[])
    with pytest.raises(SystemExit) as e:
        probe_registry(_table_a_path(tmp_path, rows), [rows[0]["dept_key"]])
    assert e.value.code == 26


def test_probe_registry_unverified_halts(tmp_path):
    """Table A rows with human_verified=False do not pass (red test #7: the whitelist must be human-checked before it is used as a filter)."""
    from roster.byline import probe_registry

    rows = build_table_a_rows()
    rows[1] = dict(rows[1], human_verified=False)
    with pytest.raises(SystemExit) as e:
        probe_registry(_table_a_path(tmp_path, rows), [rows[1]["dept_key"]])
    assert e.value.code == 26
