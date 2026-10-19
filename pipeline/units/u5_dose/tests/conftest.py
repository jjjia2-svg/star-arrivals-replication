"""Import bridge and shared fixtures for the U5 tests — follows the U3 tests/conftest.py pattern.

Path injection (anchored on the `units` directory, with assert .exists() as a drift guard):
  - U0_SRC -> `from common.* import ...` / `from identity.* import ...` (foundation, imported only, never changed)
  - U1_SRC -> `from m1_ingest._writer_util import write_rows_parquet` (deterministic parquet writer,
             owner=U1; U0 common has no parquet writer — the same reason for reuse as in U3)
  - U5_SRC -> `from m4_dose.* import ...` (this unit)

markers:
  - depends_on_u4: tests that read the definition of frozen U4 products. U4 events/paper_contrib
    are not yet fully frozen, so this unit always runs on synthetic fixtures (tests run as usual, not skipped);
    the marker only records the dependency "counts toward acceptance green once U4 is really frozen" (B-U4-FROZEN/B-EVENTS-T1).

Shared fixtures:
  - signed_dose: the three dose keys hold their fixed values (cosine / 0.0 / 0.0 in
    contracts/redlines.yaml), so the old monkeypatch injection is removed; the fixture is reduced to a sanity
    assertion that the fixed values are present (the fixture name is kept so historical test signatures do not change).
  - factories: synthetic upstream row factories (12-column WORKS / 3-column AUTHORSHIP_EDGES / 2-column REFS_EDGES /
    7-column PERSON_MAP / 14-column STAR_SET / 11-column EVENTS / 8-column PAPER_CONTRIB / 3-column WORK_TEXT),
    aligned key by key with the u0 schema.py constants — contract as code, no invented upstream fields.
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

_here = pathlib.Path(__file__).resolve()
_units = next(p for p in _here.parents if p.name == "units")

U0_SRC = _units / "u0_foundation" / "src"
U1_SRC = _units / "u1_fetch" / "src"
U5_SRC = _units / "u5_dose" / "src"
U5_ROOT = _units / "u5_dose"          # the thin CLI run_u5.py sits at the unit root

for _name, _p in [("U0", U0_SRC), ("U1", U1_SRC), ("U5", U5_SRC)]:
    assert _p.exists(), f"{_name} src is not at the expected location: {_p}"

for _p in (str(U0_SRC), str(U1_SRC), str(U5_SRC), str(U5_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "depends_on_u4: 读 U4 冻结产物口径 (events/paper_contrib 未全量冻结; "
        "合成 fixture 照跑, U4 真冻结后才计入验收绿)",
    )


# ---------------------------------------------------------------------------
# RED (three dose keys) fixed-value sanity — the tests do not set the definition, they only check the fixed values are present
# ---------------------------------------------------------------------------
@pytest.fixture
def signed_dose():
    """The three dose keys hold fixed values in contracts/redlines.yaml:
    coupling_normalization=cosine / hub_ref_idf_floor=0.0 / coverage_floor=0.0.

    Simplification: the old monkeypatch injection is redundant — RED reads the real values
    straight from the YAML at import, so the pipeline runs without injection (see
    test_run_reads_signed_dose_from_yaml_no_injection in test_run_dose). The fixture name is kept so historical test signatures do not change;
    it now only asserts that the fixed values are present and returns RED — if a value drifts, every dependent test goes red at once.
    """
    from common._redlines import RED

    assert RED["dose"]["coupling_normalization"] == "cosine", "dose value has drifted from the pinned value"
    assert RED["dose"]["hub_ref_idf_floor"] == 0.0, "dose value has drifted from the pinned value"
    assert RED["dose"]["coverage_floor"] == 0.0, "dose value has drifted from the pinned value"
    return RED


# ---------------------------------------------------------------------------
# Synthetic row factories — aligned key by key with the u0 schema constants (extra or missing keys are rejected by assert_matches_schema)
# ---------------------------------------------------------------------------
def _mk_work(work_id, year, *, work_type="article", subfield_id="2002", fwci=1.0,
             cited_by_count=1, referenced_works_count=1, has_references=True,
             is_paratext=False, is_retracted=False,
             is_in_top_1_percent=False, is_in_top_10_percent=False):
    return {
        "work_id": work_id, "publication_year": year, "work_type": work_type,
        "subfield_id": subfield_id, "fwci": fwci, "cited_by_count": cited_by_count,
        "referenced_works_count": referenced_works_count,
        "has_references": has_references, "is_paratext": is_paratext,
        "is_retracted": is_retracted, "is_in_top_1_percent": is_in_top_1_percent,
        "is_in_top_10_percent": is_in_top_10_percent,
    }


def _mk_edge(work_id, author_id, year):
    return {"work_id": work_id, "author_id": author_id, "publication_year": year}


def _mk_ref(work_id, referenced_work_id):
    return {"work_id": work_id, "referenced_work_id": referenced_work_id}


def _mk_text(work_id, *, title="title", abstract_text="abstract"):
    return {"work_id": work_id, "title": title, "abstract_text": abstract_text}


def _mk_pm(author_id, person_id, *, merge_reason="orcid", cluster_homogeneity=1.0,
           completeness=1.0, purity_flag="clean", had_orcid=True):
    return {
        "author_id": author_id, "person_id": person_id, "merge_reason": merge_reason,
        "cluster_homogeneity": cluster_homogeneity, "completeness": completeness,
        "purity_flag": purity_flag, "had_orcid": had_orcid,
    }


def _mk_star(author_id, *, name="Star", dept="monash_econ", arrival=2016,
             subfield="2002", age_bin="10-19", academic_age=15, stock=500,
             percentile=0.999, cell_n=120, is_star_1pct=True, is_star_5pct=True,
             age_eligible=True, is_foreign_poach=True):
    return {
        "author_id": author_id, "name": name, "dept": dept, "arrival": arrival,
        "subfield": subfield, "age_bin": age_bin, "academic_age": academic_age,
        "stock": stock, "percentile": percentile, "cell_n": cell_n,
        "is_star_1pct": is_star_1pct, "is_star_5pct": is_star_5pct,
        "age_eligible": age_eligible, "is_foreign_poach": is_foreign_poach,
    }


def _mk_event(event_id, star_person_id, arrival_year, t_minus_1, *,
              dept_id="I_MONASH", arrival_source="orcid_employment",
              arrival_evidence_strength="strong", modal_inst_year=True,
              prior_main_exited=True, min_tenure_ok=True, departed_year=0):
    return {
        "event_id": event_id, "dept_id": dept_id, "star_person_id": star_person_id,
        "arrival_year": arrival_year, "t_minus_1": t_minus_1,
        "arrival_source": arrival_source,
        "arrival_evidence_strength": arrival_evidence_strength,
        "modal_inst_year": modal_inst_year, "prior_main_exited": prior_main_exited,
        "min_tenure_ok": min_tenure_ok, "departed_year": departed_year,
    }


def _mk_pc(work_id, incumbent_person_id, person_id, publication_year, *,
           frac_credit=0.5, fwci=1.0, is_star_coauthored=False, subfield_id="2002"):
    return {
        "work_id": work_id, "incumbent_person_id": incumbent_person_id,
        "person_id": person_id, "publication_year": publication_year,
        "frac_credit": frac_credit, "fwci": fwci,
        "is_star_coauthored": is_star_coauthored, "subfield_id": subfield_id,
    }


@pytest.fixture
def mk():
    """Synthetic row factory namespace: mk.work / mk.edge / mk.ref / mk.text / mk.pm / mk.star / mk.event / mk.pc"""
    return SimpleNamespace(
        work=_mk_work, edge=_mk_edge, ref=_mk_ref, text=_mk_text,
        pm=_mk_pm, star=_mk_star, event=_mk_event, pc=_mk_pc,
    )
