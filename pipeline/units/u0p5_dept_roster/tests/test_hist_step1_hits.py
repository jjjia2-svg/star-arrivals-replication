"""Historical roster step 1, department circling, TDD - single-string phrase x window binding -> byline_dept_hits (+ unbound sidecar).

Each trap case is a real contamination form measured on the works_affil real data (the implementation layer of red test #7):
  - Brunswick trap: the lower-case substring 'unsw' hits New BrUNSWick (Rutgers, 2,518 rows).
  - State-name trap: a bare 'New South Wales' binds into the University of Sydney (a real string in works_affil).
  - Mixed-string trap: a journal joins all authors' affiliations into one string, the Piraeus economics department + a distant UNSW in the same string (232 rows).
  - Malaysia campus: the scope is the 11 Australian universities, Monash Malaysia is excluded (139 rows / 31 authors).
  - Noise: Centre for Health Economics (240 authors) / Faculty of Business and Economics do not hit.
Zero hits = broken pipeline -> SystemExit(EXIT_BYLINE_EMPTY_HITS_FAIL=28), never silently produce an empty table.
"""
import hashlib
import pathlib

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from roster.table_a import build_table_a_rows


def _cfgs():
    from roster.byline import build_phrase_config

    return build_phrase_config(build_table_a_rows())


def _hits(s):
    from roster.byline import match_string

    bound, _ = match_string(s, _cfgs())
    return bound


def _unbound(s):
    from roster.byline import match_string

    _, ub = match_string(s, _cfgs())
    return ub


# -- match_string unit cases (pure function) -------------------------------------------
def test_match_exact_monash():
    assert _hits("Department of Economics, Monash University, Clayton VIC 3800, Australia") == [
        ("monash_econ", "Department of Economics", "printed")
    ]


def test_match_case_insensitive_phrase():
    assert _hits("DEPARTMENT OF ECONOMICS, MONASH UNIVERSITY") == [
        ("monash_econ", "Department of Economics", "printed")
    ]


def test_no_match_health_economics_noise():
    assert _hits("Centre for Health Economics, Monash University, Melbourne") == []


def test_no_match_faculty_noise():
    assert _hits("Faculty of Business and Economics, Monash University") == []


def test_no_match_brunswick_trap():
    s = "Department of Economics, Rutgers University, 75 Hamilton Street, New Brunswick, NJ 08901"
    assert _hits(s) == []


def test_no_match_state_name_trap():
    s = "Department of Economics University of Sydney Camperdown New South Wales 2006 Australia"
    assert _hits(s) == []


def test_no_match_journal_blob_trap():
    s = (
        "Create Health, London (S.C.), United Kingdom; Department of Economics, University of "
        "Piraeus, Athens, Greece (M.R.); Department of Psychology, Deakin University (T.K.); "
        "and finally the School of Risk, University of New South Wales, Sydney (Z.W.)"
    )
    assert _hits(s) == []


def test_match_unsw_multilevel_within_window():
    s = "Department of Economics Australian Business School University of New South Wales Sydney, Australia 2052"
    assert _hits(s) == [("unsw_econ", "Department of Economics", "printed")]


def test_match_unsw_acronym_word():
    assert _hits("School of Economics, UNSW Business School, UNSW Sydney, NSW 2052") == [
        ("unsw_econ", "School of Economics", "printed")
    ]


def test_match_ebs_ampersand_dash_form():
    """University first + dash direct join = archive-stamp form (RePEc style, stamps the current affiliation onto a historical paper) -> stamped."""
    assert _hits("Monash University - Department of Econometrics & Business Statistics") == [
        ("monash_econ", "Department of Econometrics & Business Statistics", "stamped")
    ]


def test_match_style_bare_comma_reversed_is_stamped():
    """University first + bare comma directly followed by the department name (no hierarchy, no address) = stamp family (173 bare strings in the real data)."""
    assert _hits("Monash University, Department of Economics") == [
        ("monash_econ", "Department of Economics", "stamped")
    ]


def test_match_style_angle_hierarchy_is_stamped():
    """University first + angle brackets (aggregator hierarchy format, a real Yves Zenou 2015 string) -> stamped."""
    assert _hits("Monash University > Department of Economics, Monash Business School") == [
        ("monash_econ", "Department of Economics", "stamped")
    ]


def test_match_style_unsw_house_format_is_printed():
    """UNSW official printed format: university first but with a real hierarchy embedded in between ('UNSW Australia Business School,
    School of Economics, High Street...') = printed form, must never be mislabelled as a stamp (507+130 rows in the real data)."""
    assert _hits("UNSW Australia Business School, School of Economics, High Street, Sydney, NSW 2052, Australia") == [
        ("unsw_econ", "School of Economics", "printed")
    ]


def test_match_style_zenou_stamp_regression():
    """Yves Zenou golden regression: all Monash hits for 1998-2015 come from stamped strings
    ('Monash University - Department of Economics') - they must be labelled stamped,
    otherwise the person's candidate interval is pulled back to 1998 (true arrival 2016)."""
    assert _hits("Monash University - Department of Economics") == [
        ("monash_econ", "Department of Economics", "stamped")
    ]


def test_no_match_malaysia_campus_excluded():
    assert _hits("Department of Economics, Monash University Malaysia, Bandar Sunway, Selangor") == []


def test_multi_dept_one_blob_both_bound():
    s = (
        "Department of Economics, Monash University, Clayton; School of Economics, "
        "University of New South Wales, Sydney"
    )
    assert _hits(s) == [
        ("monash_econ", "Department of Economics", "printed"),
        ("unsw_econ", "School of Economics", "printed"),
    ]


def test_unbound_phrase_reported_not_dropped():
    """Department name hits but no university can be bound within the window -> unbound (manual review queue), not silently dropped (adversarial review #9)."""
    ub = _unbound("Department of Economics, University of Somewhere, Nowhere City")
    assert ("Department of Economics", "no_bind_token") in ub


# -- build_dept_hits integration (fixture parquet -> byline_dept_hits + sidecar) --------
def _fixture_works_affil(tmp_path):
    rows = [
        ("W1", "A_mon", "I56590836", ["Department of Economics, Monash University, Clayton"]),
        ("W2", "A_left", None, ["Department of Economics, Monash University"]),  # wiring (b) form: inst empty
        ("W3", "A_ub", "I999", ["Department of Economics, University of Somewhere"]),  # unbound
        ("W4", "A_none", "I888", ["Institute of Physics, ETH Zurich"]),  # unrelated
        ("W5", "A_uns", "I31746571", ["School of Economics, UNSW Sydney", "Department of Physics, UNSW"]),
        ("W1", "A_mon", "I4210", ["Department of Economics, Monash University, Clayton"]),  # duplicate string (second inst row) -> de-duplicated
        ("W6", "A_stamp", None, ["Monash University - Department of Economics"]),  # stamp form
    ]
    t = pa.table({
        "work_id": pa.array([r[0] for r in rows], type=pa.string()),
        "author_id": pa.array([r[1] for r in rows], type=pa.string()),
        "institution_id": pa.array([r[2] for r in rows], type=pa.string()),
        "raw_affiliation_strings": pa.array([r[3] for r in rows], type=pa.list_(pa.string())),
    })
    d = tmp_path / "works_affil"
    d.mkdir()
    pq.write_table(t, str(d / "part-00000.parquet"))
    return d


def test_build_dept_hits_schema_content_and_sidecar(tmp_path):
    from common.schema import BYLINE_DEPT_HITS
    from roster.byline import build_dept_hits

    out = tmp_path / "out"
    summary = build_dept_hits(_fixture_works_affil(tmp_path), _cfgs(), out)

    hits = pq.read_table(str(out / "byline_dept_hits.parquet"))
    assert hits.column_names == list(BYLINE_DEPT_HITS.keys()), "column order pinned = schema key order"
    got = hits.to_pylist()
    keyed = {(r["work_id"], r["author_id"], r["dept_key"]) for r in got}
    assert ("W1", "A_mon", "monash_econ") in keyed
    assert ("W2", "A_left", "monash_econ") in keyed, "leavers with an empty institution are recovered from the raw string (candidate layer of wiring b)"
    assert ("W5", "A_uns", "unsw_econ") in keyed
    assert ("W3", "A_ub", "monash_econ") not in keyed
    styles = {(r["work_id"], r["author_id"]): r["match_style"] for r in got}
    assert styles[("W1", "A_mon")] == "printed" and styles[("W6", "A_stamp")] == "stamped"
    # W1 + A_mon: two inst rows with the same string and phrase -> after de-duplication (work,author,dept,phrase) is unique
    assert len([r for r in got if r["work_id"] == "W1" and r["author_id"] == "A_mon"]) == 1
    none_inst = next(r for r in got if r["work_id"] == "W2")
    assert none_inst["institution_id"] is None, "empty inst stays None, no id is made up"

    ub = pq.read_table(str(out / "byline_unbound.parquet")).to_pylist()
    assert any(r["work_id"] == "W3" and r["reason"] == "no_bind_token" for r in ub), (
        "unbound goes to the sidecar review queue, not silently dropped"
    )
    assert summary["n_hits"] == 4 and summary["n_unbound"] >= 1


def test_build_dept_hits_zero_hits_halts(tmp_path):
    from roster.byline import build_dept_hits

    t = pa.table({
        "work_id": pa.array(["W9"], type=pa.string()),
        "author_id": pa.array(["A9"], type=pa.string()),
        "institution_id": pa.array(["I1"], type=pa.string()),
        "raw_affiliation_strings": pa.array([["Institute of Physics, ETH Zurich"]], type=pa.list_(pa.string())),
    })
    d = tmp_path / "works_affil"
    d.mkdir()
    pq.write_table(t, str(d / "part-00000.parquet"))
    with pytest.raises(SystemExit) as e:
        build_dept_hits(d, _cfgs(), tmp_path / "out")
    assert e.value.code == 28


def test_build_dept_hits_deterministic_and_no_arrow_schema_footer(tmp_path):
    from roster.byline import build_dept_hits

    wa = _fixture_works_affil(tmp_path)
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    build_dept_hits(wa, _cfgs(), o1)
    build_dept_hits(wa, _cfgs(), o2)
    for name in ("byline_dept_hits.parquet", "byline_unbound.parquet"):
        b1 = (o1 / name).read_bytes()
        assert hashlib.sha256(b1).hexdigest() == hashlib.sha256((o2 / name).read_bytes()).hexdigest()
        meta = pq.ParquetFile(str(o1 / name)).metadata.metadata or {}
        assert b"ARROW:schema" not in meta, "per S2: the new table does not embed the ARROW:schema (byte-stable across platforms)"


def test_build_dept_hits_unbound_deterministic_across_processes(tmp_path):
    """Adversarial review BLOCKER-1: unbound rows with the same (work,author,phrase,reason) but different raw strings are a flat key;
    the sort key must include affil_str, otherwise the row order degrades to set iteration order = PYTHONHASHSEED random ->
    bytes differ across processes (confirmed on real data: bucket=000 gives different shas under two seeds). Running twice in one process cannot detect this ->
    this test runs once under each of two different hash seeds, each in a subprocess, and asserts byte-for-byte equality."""
    import os
    import subprocess
    import sys as _sys
    import textwrap

    wa = tmp_path / "works_affil"
    wa.mkdir()
    rows = [
        ("W1", "A1", None, ["Department of Economics, University of Somewhere A"]),
        ("W1", "A1", None, ["Department of Economics, University of Somewhere B"]),
        ("W1", "A1", None, ["Department of Economics, University of Somewhere C"]),
        ("W2", "A2", "I56590836", ["Department of Economics, Monash University"]),
    ]
    t2 = pa.table({
        "work_id": pa.array([r[0] for r in rows], type=pa.string()),
        "author_id": pa.array([r[1] for r in rows], type=pa.string()),
        "institution_id": pa.array([r[2] for r in rows], type=pa.string()),
        "raw_affiliation_strings": pa.array([r[3] for r in rows], type=pa.list_(pa.string())),
    })
    pq.write_table(t2, str(wa / "part-00000.parquet"))

    script = textwrap.dedent("""
        import sys
        sys.path[:0] = sys.argv[3].split("|")
        from roster.byline import build_dept_hits, build_phrase_config
        from roster.table_a import build_table_a_rows
        build_dept_hits(sys.argv[1], build_phrase_config(build_table_a_rows()), sys.argv[2])
    """)
    _units = pathlib.Path(__file__).resolve()
    while _units.name != "units":
        _units = _units.parent
    paths = "|".join([str(_units / "u0_foundation" / "src"),
                      str(_units / "u0p5_dept_roster" / "src")])
    shas = []
    for seed, sub in (("0", "s0"), ("7", "s7")):
        out = tmp_path / sub
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([_sys.executable, "-c", script, str(wa), str(out), paths],
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-500:]
        shas.append(hashlib.sha256((out / "byline_unbound.parquet").read_bytes()).hexdigest())
    assert shas[0] == shas[1], "unbound must be byte-identical across processes / hash seeds (byte-determinism red line)"


def test_window_boundary_pinned_gap79_in_gap80_out():
    """Adversarial review LOW-4: the real meaning of the '+-80 window' is a max gap of 79 (gap 80 is outside the window) - pinned to prevent drift."""
    pad_in = "x" * 78   # gap = 1 (space) + 78 = 79 -> inside the window
    pad_out = "x" * 79  # gap = 80 -> outside the window
    assert _hits(f"Department of Economics {pad_in}Monash") != []
    assert _hits(f"Department of Economics {pad_out}Monash") == []


def test_lower_fold_length_preserving_guard():
    """Adversarial review MED-2: phrases are in lower() coordinates, token/stamp slices in raw-string coordinates - 'İ'.lower() changes the length
    and misaligns them (the binding/window/stamp decisions flip). Guard: folding must preserve length."""
    from roster.byline import _fold_lower

    s = "İ Monash University - Department of Economics"
    assert len(_fold_lower(s)) == len(s), "length must not change after folding (consistent coordinate system)"
    # end to end: an İ prefix must not disturb stamp detection
    assert _hits(s) == [("monash_econ", "Department of Economics", "stamped")]


# -- A13: the case-insensitive substring path of _token_spans must use the same length-preserving coordinates as the phrases -------------
def test_token_spans_case_insensitive_uses_length_preserving_fold():
    """A13: the case-insensitive substring path uses s.lower() (changes length) -> misaligned with the phrase coordinates (_fold_lower preserves length).
    'İ'.lower() is 2 chars; locating with s.lower() shifts the whole token span right, and slicing back into the raw string no longer gives the real token."""
    from roster.byline import _token_spans

    s = "İ Monash University"  # İ before the token; s.lower() inserts a combining dot, so every later coordinate is +1
    spans = _token_spans(s, {"text": "Monash", "case_sensitive": False, "word_boundary": False})
    assert spans == [(2, 8)], "span must use original-string coordinates (length-preserving fold) — s.lower() would wrongly give (3,9)"
    assert s[spans[0][0]:spans[0][1]] == "Monash", "slicing the original string by the span must give exactly the token"


def test_izcap_prefix_does_not_push_bind_token_out_of_window():
    """A13 end to end (lost binding): token coordinates must be in the same system as phrase coordinates. With an İ prefix s.lower() shifts Monash
    right by +1, gap 79 (in window) -> 80 (out of window) -> the hit is silently dropped. With length-preserving folding it stays in the window and the hit is kept."""
    s = "İDepartment of Economics " + "x" * 78 + "Monash"   # true gap = 79 (inside the window)
    assert _hits(s) == [("monash_econ", "Department of Economics", "printed")], (
        "a leading İ must not push the Monash token out of the ±80 window (coordinate system must be consistent)"
    )


def test_izcap_prefix_does_not_flip_stamp_label():
    """A13 end to end (stamp flip): a token span shifted right by 1 misaligns the start of the separator slice
    affil_str[sp[1]:ps] of _occurrence_style and swallows the first non-noise letter -> a printed form is misjudged as a stamp.
    Here the 'B' of 'Buniversity' is swallowed by the misalignment and becomes 'university' (noise) -> wrongly stamped;
    with length-preserving folding the slice starts correctly = printed."""
    s = "İMonashBuniversity Department of Economics"
    assert _hits(s) == [("monash_econ", "Department of Economics", "printed")], (
        "a misaligned slice would turn 'Buniversity' (not noise) into 'university' (noise) -> wrongly stamped; with length-preserving folding it should be printed"
    )


def test_build_dept_hits_none_element(tmp_path):
    from roster.byline import build_dept_hits

    t2 = pa.table({
        "work_id": pa.array(["W1"], type=pa.string()),
        "author_id": pa.array(["A1"], type=pa.string()),
        "institution_id": pa.array([None], type=pa.string()),
        "raw_affiliation_strings": pa.array(
            [[None, "Department of Economics, Monash University"]], type=pa.list_(pa.string())),
    })
    wa = tmp_path / "works_affil"
    wa.mkdir()
    pq.write_table(t2, str(wa / "part-00000.parquet"))
    summary = build_dept_hits(wa, _cfgs(), tmp_path / "out")
    assert summary["n_hits"] == 1, "None elements are skipped, the other strings match as usual"


def test_build_dept_hits_later_file_flattened_halts(tmp_path):
    """Adversarial review MED-3: probing only the first file is not enough - the scanner itself checks the raw column type file by file;
    if a later file is flattened -> HALT 25, never silently drop rows (HALT beats silence)."""
    wa = tmp_path / "works_affil"
    wa.mkdir()
    ok = pa.table({
        "work_id": pa.array(["W1"], type=pa.string()),
        "author_id": pa.array(["A1"], type=pa.string()),
        "institution_id": pa.array(["I56590836"], type=pa.string()),
        "raw_affiliation_strings": pa.array(
            [["Department of Economics, Monash University"]], type=pa.list_(pa.string())),
    })
    bad = pa.table({
        "work_id": pa.array(["W2"], type=pa.string()),
        "author_id": pa.array(["A2"], type=pa.string()),
        "institution_id": pa.array(["I56590836"], type=pa.string()),
        "raw_affiliation_strings": pa.array(
            ["Department of Economics, Monash University"], type=pa.string()),
    })
    pq.write_table(ok, str(wa / "part-00000.parquet"))
    pq.write_table(bad, str(wa / "part-00001.parquet"))
    from roster.byline import build_dept_hits

    with pytest.raises(SystemExit) as e:
        build_dept_hits(wa, _cfgs(), tmp_path / "out")
    assert e.value.code == 25


def test_prefilter_parametrized_apostrophe_phrase_safe(tmp_path):
    """Adversarial review LOW-1: the pre-filter SQL must be parameterised - a phrase with an apostrophe (a future King's) does not break it and is equivalent."""
    from roster.byline import build_dept_hits

    cfgs = _cfgs()
    cfgs[0] = dict(cfgs[0], phrases=list(cfgs[0]["phrases"]) + ["King's Department of Economics"])
    wa = _fixture_works_affil(tmp_path)
    o1, o2 = tmp_path / "q0", tmp_path / "q1"
    build_dept_hits(wa, cfgs, o1, use_prefilter=False)
    build_dept_hits(wa, cfgs, o2, use_prefilter=True)
    assert (o1 / "byline_dept_hits.parquet").read_bytes() == (o2 / "byline_dept_hits.parquet").read_bytes()


def test_build_dept_hits_prefilter_equivalence(tmp_path):
    """duckdb pre-filter = semantic superset (phrase substring ILIKE); outputs with the switch on and off must be byte-for-byte identical."""
    from roster.byline import build_dept_hits

    wa = _fixture_works_affil(tmp_path)
    o1, o2 = tmp_path / "p0", tmp_path / "p1"
    build_dept_hits(wa, _cfgs(), o1, use_prefilter=False)
    build_dept_hits(wa, _cfgs(), o2, use_prefilter=True)
    for name in ("byline_dept_hits.parquet", "byline_unbound.parquet"):
        assert (o1 / name).read_bytes() == (o2 / name).read_bytes()
