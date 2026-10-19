"""Department-name phrase config TDD for historical roster step 1 - phrase whitelist + bind/exclude tokens + frozen SHA.

The design is grounded entirely in the works_affil real-data evidence scan (evidence_scan.duckdb, 403,107 candidate strings):
  - Binding must happen at the "single byline string" level, with a university token within +-window (a row-level institution_id
    would wrongly bind a co-appointed author's economics department at another school; a journal-wide mixed string would bind Piraeus's economics department to UNSW).
  - The lower-case substring "unsw" hits "New BrUNSWick" (Rutgers, 2,518 rows) -> the UNSW abbreviation must be a case-sensitive whole word.
  - A bare "New South Wales" is a state name and would bind into the University of Sydney/Macquarie -> only the full name + the whole word UNSW are allowed.
  - The Monash Malaysia campus (31 authors) is out of scope (the 11 Australian universities) -> exclude token.
Phrase source = Table A dept_name_variants (single authoritative source); the config only adds the binding mechanism and keeps no phrases of its own.
"""
import hashlib

from roster.table_a import build_table_a_rows


def test_build_phrase_config_from_table_a():
    from roster.byline import build_phrase_config

    cfgs = {c["dept_key"]: c for c in build_phrase_config(build_table_a_rows())}
    assert set(cfgs) == {"monash_econ", "unsw_econ"}

    for dk, row in ((dk, r) for dk in cfgs for r in build_table_a_rows() if r["dept_key"] == dk):
        assert cfgs[dk]["phrases"] == row["dept_name_variants"], "the single authoritative source of phrases = Table A dept_name_variants"

    mon = cfgs["monash_econ"]
    assert "Malaysia" in mon["exclude_tokens"], "the Monash Malaysia campus is outside the 11 Australian universities in scope"
    assert any(t["text"] == "Monash" for t in mon["bind_tokens"])

    uns = cfgs["unsw_econ"]
    texts = {t["text"] for t in uns["bind_tokens"]}
    assert "University of New South Wales" in texts
    unsw_tok = next(t for t in uns["bind_tokens"] if t["text"] == "UNSW")
    assert unsw_tok["case_sensitive"] is True and unsw_tok["word_boundary"] is True, (
        "UNSW must be case-sensitive and whole-word, else it matches New BrUNSWick (confirmed on real data: 2,518 Rutgers rows)"
    )
    assert "New South Wales" not in texts, "a bare state name would bind all of Sydney University/Macquarie (confirmed on real data)"

    assert all(c["window_chars"] == 80 for c in cfgs.values())


def test_build_phrase_config_unknown_dept_raises():
    """bind/exclude tokens must be curated school by school; a dept_key that is not registered never silently gets a default."""
    import pytest

    from roster.byline import build_phrase_config

    ghost = dict(build_table_a_rows()[0])
    ghost["dept_key"] = "ghost_econ"
    with pytest.raises(KeyError):
        build_phrase_config([ghost])


def test_write_phrase_config_deterministic_sha_and_roundtrip(tmp_path):
    from roster.byline import build_phrase_config, load_phrase_config, write_phrase_config

    cfgs = build_phrase_config(build_table_a_rows())
    d1, d2 = tmp_path / "c1", tmp_path / "c2"
    sha1 = write_phrase_config(cfgs, d1)
    sha2 = write_phrase_config(cfgs, d2)

    assert set(sha1) == {"monash_econ", "unsw_econ"}
    for dk in sha1:
        f1, f2 = d1 / f"{dk}.yaml", d2 / f"{dk}.yaml"
        assert f1.exists()
        assert sha1[dk] == sha2[dk] == hashlib.sha256(f1.read_bytes()).hexdigest(), (
            "config frozen SHA: two writes of the same input are byte-identical (the reproducibility proof recorded in the manifest)"
        )
        assert f1.read_bytes() == f2.read_bytes()

    back = load_phrase_config(d1, ["monash_econ", "unsw_econ"])
    assert back == cfgs, "round-trip is lossless"
