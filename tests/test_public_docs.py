"""The public documents agree with the data they describe.

README.md states the event counts of the report's data (data/report/cal/counts.json), the number of
headline estimates the default run re-estimates and checks (the cell lists config/r1/cells/M.tsv and
M_evcl.tsv), the share of the economics roster marked `human_verified`, the seeds (config/seeds.yaml)
and the references. The checks that read data/report skip until it is committed.
"""
from __future__ import annotations

import csv
import json
import pathlib
import re
from collections import Counter

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
REPORT = REPO / "data" / "report"
CELL_LISTS = ("config/r1/cells/M.tsv", "config/r1/cells/M_evcl.tsv")
DOCS = ("README.md", "CHANGELOG.md", "CITATION.cff", "LICENSE", "LICENSE-DATA.md", "THIRD_PARTY.md",
        "docs/AI_USAGE.md", "data/README.md", "pipeline/NOT_REPRODUCIBLE.md", "analysis/paper/README.md",
        "pipeline/aws/r1/README.md", "analysis/estimation/README.md", "analysis/expected/SOURCES.md")
#: values measured after the final run; each is filled in from its record before release
PLACEHOLDERS = {"RUNTIME", "PEAK_MEMORY"}
#: wording that says who checked the roster rows; the documents state what the column records instead
WHO_CHECKED = re.compile(r"by hand|hand-check|by a person|a person read", re.I)
CJK = re.compile("[　-〿㐀-䶿一-鿿＀-￯]")


def stacks(paths) -> Counter:
    """Cell rows per R stack over the given cell lists (tab-separated, column `stack`)."""
    n: Counter = Counter()
    for p in paths:
        with open(p, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                n[row["stack"]] += 1
    return n


def _num(s: str) -> int:
    return int(s.replace(",", ""))


def readme_cells(text: str) -> tuple[int, int, int]:
    """(re-estimated, total, checked) from the README's sentence on the default run."""
    m = re.search(r"re-estimates\s+(\d+)\s+of\s+the\s+(\d+)\s+headline\s+estimates", text)
    c = re.search(r"checks\s+the\s+other\s+(\d+)", text)
    assert m and c, "the README no longer says how many headline estimates the default run re-estimates and checks"
    return int(m.group(1)), int(m.group(2)), int(c.group(1))


def readme_events(text: str) -> tuple[int, int, int, int]:
    """(total, economics, chemistry, mathematics and statistics) from the README's overview."""
    m = re.search(r"([\d,]+)\s+star\s+arrivals", text)
    f = re.search(r"economics\s+([\d,]+),\s+chemistry\s+([\d,]+)\s+and\s+mathematics\s+and\s+statistics\s+([\d,]+)",
                  text)
    assert m and f, "the README no longer states the event counts"
    return (_num(m.group(1)),) + tuple(_num(g) for g in f.groups())


def roster_claim(text: str) -> tuple[int, int]:
    """(rows marked `human_verified`, all rows) of the economics roster as a document states them."""
    m = re.search(r"([\d,]+)\s+of\s+the\s+([\d,]+)\s+economics\s+roster\s+rows", text)
    assert m, "the document no longer states the human_verified share of the economics roster"
    return _num(m.group(1)), _num(m.group(2))


def section(text: str, heading: str) -> str:
    """The body of a `## ` or `### ` section, up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    m = re.search(r"^" + re.escape(heading) + r"\n(.*?)(?=^#{1," + str(len(level)) + r"} |\Z)", text, re.S | re.M)
    assert m, f"no section {heading!r}"
    return m.group(1)


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


# ---- the helpers, on toy inputs ----------------------------------------------------------------------------
def test_stacks_counts_rows_per_stack(tmp_path):
    a, b = tmp_path / "a.tsv", tmp_path / "b.tsv"
    a.write_text("label\tstack\nX\trmac\nY\trcloud\nZ\trmac\n", encoding="utf-8")
    b.write_text("label\tstack\nW\trmac\n", encoding="utf-8")
    assert stacks((a, b)) == Counter({"rmac": 3, "rcloud": 1})


def test_the_sentence_readers():
    text = ("It uses 1,234 star arrivals: economics 600, chemistry 334 and mathematics and statistics 300. "
            "The run re-estimates 9 of the 12 headline estimates and checks the other 3. "
            "In all, 40 of the 1,000 economics roster\nrows are marked `human_verified`.\n\n"
            "## A\none\n### B\ntwo\n## C\nthree\n")
    assert readme_events(text) == (1234, 600, 334, 300)
    assert readme_cells(text) == (9, 12, 3)
    assert roster_claim(text) == (40, 1000)
    assert section(text, "## A") == "one\n### B\ntwo\n"
    assert section(text, "### B") == "two\n"
    assert section(text, "## C") == "three\n"
    with pytest.raises(AssertionError):
        readme_cells("re-estimates all of them")


# ---- the documents ------------------------------------------------------------------------------------------
def test_every_public_document_exists_in_english_with_only_the_declared_placeholders():
    for rel in DOCS:
        assert (REPO / rel).is_file(), f"{rel} is missing"
        text = _read(rel)
        assert not CJK.search(text), f"{rel} has Chinese text"
        extra = set(re.findall(r"\{\{([A-Z_]+)\}\}", text)) - PLACEHOLDERS
        assert not extra, f"{rel}: undeclared placeholders {sorted(extra)}"


def test_readme_cell_counts_match_the_cell_lists():
    n = stacks(REPO / p for p in CELL_LISTS)
    assert set(n) == {"rmac", "rcloud"}, n
    assert readme_cells(_read("README.md")) == (n["rmac"], n["rmac"] + n["rcloud"], n["rcloud"])


def test_a_documented_paths_config_is_an_absolute_path():
    """Most tools refuse a relative SAR_PATHS_CONFIG, so the documents give it as $PWD/<file>."""
    seen = 0
    for rel in DOCS:
        for m in re.finditer(r"SAR_PATHS_CONFIG=([^\s`|]+)", _read(rel)):
            seen += 1
            assert m.group(1).startswith(("$PWD/", "/")), f"{rel}: SAR_PATHS_CONFIG={m.group(1)} is a relative path"
    assert seen, "no public document shows how to select another paths config"


def test_readme_event_counts_match_the_report_data():
    counts_file = REPORT / "cal" / "counts.json"
    if not counts_file.is_file():
        pytest.skip("data/report is not committed yet")
    c = json.loads(counts_file.read_text(encoding="utf-8"))
    e = c["events"]
    want = (c["events_total"], e["econ"], e["chemistry"], e["math_stats"])
    assert want[0] == sum(want[1:])
    assert readme_events(_read("README.md")) == want
    assert f"{want[0]} events" in _read("CHANGELOG.md")


def test_the_roster_checks_are_stated_as_what_the_column_records():
    """README and docs/AI_USAGE.md say how many rows are marked `human_verified`. No document says the
    roster rows were checked by hand or by a person: the column records the verification, not who did it."""
    for rel in ("README.md", "docs/AI_USAGE.md"):
        text = _read(rel)
        assert re.search(r"economics\s+roster\s+rows\s+are\s+marked\s+`human_verified`", text), rel
        hit = WHO_CHECKED.search(text)
        assert not hit, f"{rel}: {hit.group(0)!r}"
    for para in re.split(r"\n\s*\n", _read("pipeline/NOT_REPRODUCIBLE.md")):
        hit = WHO_CHECKED.search(para) if re.search(r"roster|human_verified", para) else None
        assert not hit, f"pipeline/NOT_REPRODUCIBLE.md: {hit.group(0)!r} in {para[:160]!r}"


def test_only_default_runtime_and_peak_memory_may_await_the_e2e_summary():
    text = _read("README.md")
    pending = set(re.findall(r"\{\{([A-Z_]+)\}\}", text))
    assert not pending or pending == PLACEHOLDERS
    assert all(text.count("{{" + key + "}}") <= 1 for key in PLACEHOLDERS)
    assert "run_all.secs" in text and "run_all.peak_gib" in text
    assert "data/report/custody/RESOURCES.md" in text
    for rel in DOCS:
        if rel != "README.md":
            assert not re.findall(r"\{\{([A-Z_]+)\}\}", _read(rel)), rel
    assert 'date-released: "2026-10-19"' in _read("CITATION.cff")
    assert "1.0 (2026-10-19)" in _read("CHANGELOG.md")


def test_reference_ledgers_have_only_numbers_flags_and_nulls_and_are_pinned():
    import hashlib
    files = sorted((REPORT / "paper_numbers").glob("data_numbers_2026-10-24*.json"))
    assert len(files) == 10
    manifest = (REPORT / "paper_numbers/MANIFEST.sha256").read_text(encoding="utf-8")

    def check(obj):
        if isinstance(obj, dict):
            assert all(not k.startswith("_") for k in obj)
            for value in obj.values():
                check(value)
        elif isinstance(obj, list):
            for value in obj:
                check(value)
        else:
            assert obj is None or isinstance(obj, (int, float))

    for path in files:
        check(json.loads(path.read_bytes()))
        line = f"{hashlib.sha256(path.read_bytes()).hexdigest()}  paper_numbers/{path.name}"
        assert line in manifest.splitlines()


def test_the_readme_lists_every_seed():
    """Every seed in config/seeds.yaml appears in the README's seeds section."""
    seeds = re.findall(r"^\w+:\s*(\d+)", _read("config/seeds.yaml"), re.M)
    assert len(seeds) == 4, seeds
    body = section(_read("README.md"), "### Random seeds")
    assert "config/seeds.yaml" in body
    for v in seeds:
        assert re.search(r"(?<![\d,])" + v + r"(?![\d,])", body), f"seed {v} is not in the README"


def test_the_readme_references_name_the_sources_and_both_estimator_versions():
    """A References section before the licence cites the data sources and the estimator package at the
    versions the two R stacks pin."""
    text = _read("README.md")
    assert text.index("\n## References\n") < text.index("\n## Licence\n")
    refs = section(text, "## References")
    pins = {"setup/R_VERSIONS.txt": r"^DIDmultiplegtDYN==(\S+)$",
            "config/r1/expected_versions.txt": r"^rcloud\tDIDmultiplegtDYN\t(\S+)$"}
    for rel, rx in pins.items():
        m = re.search(rx, _read(rel), re.M)
        assert m and f"version {m.group(1)}" in refs, (rel, m and m.group(1))
    for name in ("OpenAlex", "26 June 2026", "Natural Earth", "ETOPO5", "Australian Bureau of Statistics"):
        assert name in refs, name


def test_the_second_stack_install_names_the_pinned_rust_toolchain():
    """polars for R is built from source with the toolchain pipeline/aws/r1/build_env.sh pins (the R build
    ignores the package's own rust-toolchain.toml), so the install steps must name the same one."""
    m = re.search(r'^RUST_TOOLCHAIN="([^"]+)"', _read("pipeline/aws/r1/build_env.sh"), re.M)
    assert m
    text = _read("analysis/estimation/README.md")
    assert f"rustup toolchain install {m.group(1)}" in text
    assert f"RUSTUP_TOOLCHAIN={m.group(1)}" in text
    assert "config/r1/r_runtime_apt.txt" in text and "cmake" in text and "pkg-config" in text


def test_the_human_verified_roster_share_matches_the_report_data():
    roster = REPORT / "cal" / "roster_econ_verified_2026-10.parquet"
    if not roster.is_file():
        pytest.skip("data/report is not committed yet")
    import pyarrow.parquet as pq
    t = pq.read_table(roster, columns=["human_verified"]).column("human_verified").to_pylist()
    want = (sum(1 for v in t if v is True), len(t))
    for rel in ("README.md", "docs/AI_USAGE.md"):
        assert roster_claim(_read(rel)) == want, rel
