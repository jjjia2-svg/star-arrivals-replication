"""U6 test import bridge + synthetic-world fixture, following the U5 tests/conftest.py pattern.

Path injection (anchored at the `units` directory):
  - U0_SRC -> common.* / identity.* (foundation, import only, never changed)
  - U1_SRC -> m1_ingest._writer_util (deterministic parquet writer, owner=U1)
  - U6_SRC -> m7b_assemble.* / m7c_gates.* / m7d_power.* (this unit)
  - U6_ROOT -> run_u6 thin CLI

markers:
  - depends_on_u345: tests that read the definitions of upstream frozen products. The upstream dose/output/
    star_set/events are truly frozen (u5_ship_2026-07-10 + u4_ship_2026-07-10c),
    and the synthetic fixture is aligned key by key with what is on disk; the marker registers the dependency and the tests run as usual.

Synthetic world (zenou_world): aligned key by key with the frozen on-disk reality:
  Yves Zenou anchor (author A5017376589 -> person P_Z; arrival 2016 Monash I56590836;
  first_pub 1991 -> academic_age=24 = (2016-1)-1991; is_star_1pct; multiple author fragments
  folded into a single person; works_count=583 summed from panel n_works_year).
"""
from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace

_here = pathlib.Path(__file__).resolve()
_units = next(p for p in _here.parents if p.name == "units")

U0_SRC = _units / "u0_foundation" / "src"
U1_SRC = _units / "u1_fetch" / "src"
U6_SRC = _units / "u6_assemble" / "src"
U6_ROOT = _units / "u6_assemble"

for _name, _p in [("U0", U0_SRC), ("U1", U1_SRC), ("U6", U6_SRC)]:
    assert _p.exists(), f"{_name} src is not at the expected location: {_p}"

for _p in (str(U0_SRC), str(U1_SRC), str(U6_SRC), str(U6_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "depends_on_u345: 读 U3/U4/U5/U0.5 冻结产物口径 (合成 fixture 逐键对齐"
        "盘上 2026-07-10 冻结现实; 上游变形则此依赖失效)",
    )


# ---------------------------------------------------------------------------
# Synthetic row factories, aligned key by key with the u0 schema constants (extra or missing keys are rejected by assert_matches_schema)
# ---------------------------------------------------------------------------
def _mk_pm(author_id, person_id, *, merge_reason="block_cluster",
           cluster_homogeneity=None, completeness=None, purity_flag=None,
           had_orcid=False):
    return {
        "author_id": author_id, "person_id": person_id,
        "merge_reason": merge_reason, "cluster_homogeneity": cluster_homogeneity,
        "completeness": completeness, "purity_flag": purity_flag,
        "had_orcid": had_orcid,
    }


def _mk_star(author_id, *, name="Star", dept="monash_econ", arrival=2016,
             subfield="2002", age_bin="22-25", academic_age=15, stock=500,
             percentile=0.999, cell_n=120, is_star_1pct=True, is_star_5pct=True,
             age_eligible=True, is_foreign_poach=True):
    return {
        "author_id": author_id, "name": name, "dept": dept, "arrival": arrival,
        "subfield": subfield, "age_bin": age_bin, "academic_age": academic_age,
        "stock": stock, "percentile": percentile, "cell_n": cell_n,
        "is_star_1pct": is_star_1pct, "is_star_5pct": is_star_5pct,
        "age_eligible": age_eligible, "is_foreign_poach": is_foreign_poach,
    }


def _mk_event(event_id, star_author_id, arrival_year, *, dept_id="I56590836",
              arrival_source="official_roster",
              arrival_evidence_strength="strong", modal_inst_year=True,
              prior_main_exited=True, min_tenure_ok=True, departed_year=None):
    return {
        "event_id": event_id, "dept_id": dept_id,
        "star_person_id": star_author_id,           # Real data: holds the raw author_id
        "arrival_year": arrival_year, "t_minus_1": arrival_year - 1,
        "arrival_source": arrival_source,
        "arrival_evidence_strength": arrival_evidence_strength,
        "modal_inst_year": modal_inst_year, "prior_main_exited": prior_main_exited,
        "min_tenure_ok": min_tenure_ok, "departed_year": departed_year,
    }


def _mk_dose(incumbent, star_pid, event_id, *, coupling_share=0.5,
             topic_cos=0.1, embed_cos=None, coupling_coverage=0.6,
             frozen_at_year=2015, degree=1, degree2_bridge_frozen=True,
             boundary_sensitive=False):
    return {
        "incumbent_person_id": incumbent, "star_person_id": star_pid,
        "event_id": event_id, "coupling_share": coupling_share,
        "topic_cos": topic_cos, "embed_cos": embed_cos,
        "coupling_coverage": coupling_coverage, "frozen_at_year": frozen_at_year,
        "degree": degree, "degree2_bridge_frozen": degree2_bridge_frozen,
        "boundary_sensitive": boundary_sensitive,
    }


def _mk_output(incumbent, year, *, pub_count=1, pub_count_ex_star=1,
               n_works_frac=0.5, fwci_frac=1.0, fwci_frac_ex_star=0.8,
               fwci_full=2.0, fwci_full_ex_star=1.6, fwci_mean=1.0,
               fwci_mean_ex_star=0.9, quality=None):
    return {
        "incumbent_person_id": incumbent, "year": year, "pub_count": pub_count,
        "pub_count_ex_star": pub_count_ex_star, "n_works_frac": n_works_frac,
        "fwci_frac": fwci_frac, "fwci_frac_ex_star": fwci_frac_ex_star,
        "fwci_full": fwci_full, "fwci_full_ex_star": fwci_full_ex_star,
        "fwci_mean": fwci_mean, "fwci_mean_ex_star": fwci_mean_ex_star,
        "quality": quality,
    }


def _mk_roster(dept_key, author_id, *, display_name="Person", year_start=2000,
               year_end=2026, evidence="official_roster", confidence="high",
               human_verified=False):
    return {
        "dept_key": dept_key, "author_id": author_id,
        "display_name": display_name, "year_start": year_start,
        "year_end": year_end, "evidence": evidence, "confidence": confidence,
        "human_verified": human_verified,
    }


def _mk_registry(dept_key, openalex_inst_id, *, university="U",
                 dept_name_variants=("Department of Economics",),
                 is_business_school=False,
                 subfield_primary=("Economics and Econometrics",),
                 subfield_robustness_flagged=(), subfield_excluded=("Finance",),
                 source="manual", human_verified=True):
    return {
        "dept_key": dept_key, "university": university,
        "openalex_inst_id": openalex_inst_id,
        "dept_name_variants": list(dept_name_variants),
        "is_business_school": is_business_school,
        "subfield_primary": list(subfield_primary),
        "subfield_robustness_flagged": list(subfield_robustness_flagged),
        "subfield_excluded": list(subfield_excluded),
        "source": source, "human_verified": human_verified,
    }


def _mk_panel(person_id, year, *, primary_affil_id="AFFIL_NONE", n_works_year=1,
              first_pub_year=1991):
    # The U6 panel slice takes only 5 columns (io_real projection), not all 8 PANEL columns.
    return {
        "person_id": person_id, "year": year,
        "primary_affil_id": primary_affil_id, "n_works_year": n_works_year,
        "first_pub_year": first_pub_year,
    }


@pytest.fixture
def mk():
    """Factory namespace: mk.pm/star/event/dose/output/roster/registry/panel"""
    return SimpleNamespace(
        pm=_mk_pm, star=_mk_star, event=_mk_event, dose=_mk_dose,
        output=_mk_output, roster=_mk_roster, registry=_mk_registry,
        panel=_mk_panel,
    )


# ---------------------------------------------------------------------------
# Synthetic world: Yves Zenou anchor + one 5pct-only event + a UNSW department (two universities, nt-pool empty)
# ---------------------------------------------------------------------------
_QUAD_U4 = {
    "source_snapshot_merkle": "snap:aaa", "config_sha": "cfg_u4",
    "rule_version": "redlines_v4_signed_2026-07-05", "stars_set_hash": "ssh_1",
}
_QUAD_U5 = {
    "source_snapshot_merkle": "snap:aaa", "config_sha": "cfg_u5",
    "rule_version": "redlines_v4_signed_2026-07-05", "stars_set_hash": "ssh_1",
}


def build_zenou_world():
    """Synthetic two-university world (returns a dict, each table a list[dict]).

    People:
      - Yves Zenou: authors AZ1/AZ2 fold into P_Z; star at 1pct+5pct; arrives at Monash in 2016;
        academic_age=24 (-> first publication 1991).
      - S5: author AS5 -> P_S5; 5pct star only; arrives at UNSW in 2019.
      - Dangerous namesake: ANAMESAKE -> P_NAMESAKE (a separate person, not merged into the cluster).
      - Incumbent I1 (Monash 2000-2026, first publication 2000, with output years and empty-output years)
      - Incumbent I2 (Monash 2010-2018, leaves -> no later publication = complete exit, first publication 2005)
      - Incumbent I3 (UNSW interval null-null -> panel late binding 2012-2026, first publication 2010)
      - Incumbent I4 (Monash, only 1 publication year -> pop-min violation case, first publication 2025)
    """
    pm = [
        _mk_pm("AZ1", "P_Z", had_orcid=True), _mk_pm("AZ2", "P_Z"),
        _mk_pm("AS5", "P_S5"), _mk_pm("ANAMESAKE", "P_NAMESAKE"),
        _mk_pm("AI1", "P_I1"), _mk_pm("AI2", "P_I2"), _mk_pm("AI3", "P_I3"),
        _mk_pm("AI4", "P_I4"),
    ]
    star_set = [
        _mk_star("AZ1", name="Yves Zénou", dept="monash_econ", arrival=2016,
                 academic_age=24, is_star_1pct=True, is_star_5pct=True),
        _mk_star("AS5", name="Five Pct", dept="unsw_econ", arrival=2019,
                 academic_age=8, is_star_1pct=False, is_star_5pct=True),
        _mk_star("ANAMESAKE", name="Namesake Example", dept="monash_econ", arrival=2016,
                 academic_age=24, is_star_1pct=False, is_star_5pct=False,
                 is_foreign_poach=False),
    ]
    events = [
        _mk_event("AZ1:2016", "AZ1", 2016, dept_id="I56590836"),
        _mk_event("AS5:2019", "AS5", 2019, dept_id="I31746571"),
    ]
    dose = {
        "p01": [
            _mk_dose("P_I1", "P_Z", "AZ1:2016", coupling_share=0.4, degree=1),
            _mk_dose("P_I2", "P_Z", "AZ1:2016", coupling_share=0.0, degree=2,
                     degree2_bridge_frozen=False),
            _mk_dose("P_I4", "P_Z", "AZ1:2016", coupling_share=0.1, degree=2),
        ],
        "p05": [
            _mk_dose("P_I1", "P_Z", "AZ1:2016", coupling_share=0.4, degree=1),
            _mk_dose("P_I2", "P_Z", "AZ1:2016", coupling_share=0.0, degree=2,
                     degree2_bridge_frozen=False),
            _mk_dose("P_I4", "P_Z", "AZ1:2016", coupling_share=0.1, degree=2),
            _mk_dose("P_I3", "P_S5", "AS5:2019", coupling_share=0.2, degree=1,
                     frozen_at_year=2018),
        ],
    }
    # OUTPUT: only rows for years with output (some years of 2011-2021 within the window).
    output = {
        "p01": [
            _mk_output("P_I1", 2013), _mk_output("P_I1", 2016),
            _mk_output("P_I1", 2018, fwci_mean=None, fwci_mean_ex_star=None),
            _mk_output("P_I2", 2012),
            _mk_output("P_I2", 2016),      # I2 has no publication after leaving in 2018 (complete exit)
            _mk_output("P_I4", 2025),      # I4 has only 1 publication year (outside the window)
            _mk_output("P_I3", 2019),
        ],
        "p05": [
            _mk_output("P_I1", 2013), _mk_output("P_I1", 2016),
            _mk_output("P_I1", 2018, fwci_mean=None, fwci_mean_ex_star=None),
            _mk_output("P_I2", 2012),
            _mk_output("P_I2", 2016),
            _mk_output("P_I4", 2025),
            _mk_output("P_I3", 2019, fwci_frac=0.9, fwci_frac_ex_star=0.7),
        ],
    }
    roster = [
        _mk_roster("monash_econ", "AI1", year_start=2000, year_end=2026),
        _mk_roster("monash_econ", "AI2", year_start=2010, year_end=2018),
        _mk_roster("monash_econ", "AI4", year_start=None, year_end=None),
        _mk_roster("unsw_econ", "AI3", year_start=None, year_end=None),
        _mk_roster("unsw_econ", None, display_name="No OpenAlex Id"),
    ]
    registry = [
        _mk_registry("monash_econ", "I56590836", university="Monash University"),
        _mk_registry("unsw_econ", "I31746571", university="UNSW Sydney"),
    ]
    panel = (
        # Yves Zenou: first publication 1991 + works_count=583 (35 rows summing to it)
        [_mk_panel("P_Z", 1991, n_works_year=3, first_pub_year=1991)]
        + [_mk_panel("P_Z", y, n_works_year=29, first_pub_year=1991)
           for y in range(1992, 2012)]
        # 583 = 3 + 20*29 = 583 ✓
        + [_mk_panel("P_I1", y, first_pub_year=2000,
                     primary_affil_id="I56590836") for y in range(2000, 2027)]
        + [_mk_panel("P_I2", y, first_pub_year=2005,
                     primary_affil_id="I56590836") for y in (2005, 2012, 2016)]
        + [_mk_panel("P_I3", y, first_pub_year=2010,
                     primary_affil_id="I31746571") for y in range(2012, 2027)]
        + [_mk_panel("P_I4", 2025, first_pub_year=2025,
                     primary_affil_id="I56590836")]
    )
    return {
        "person_map": pm, "star_set": star_set, "events": events,
        "dose": dose, "output": output, "roster": roster, "registry": registry,
        "panel": panel, "work_first_pub": {},
        "upstream_provenance": {"u4": dict(_QUAD_U4), "u5": dict(_QUAD_U5)},
        "upstream_diag": {
            "dose_p01": {"mnar_robustness_required": True},
            "dose_p05": {"mnar_robustness_required": True},
            "output": {"p01": {"mnar_robustness_required": True},
                       "p05": {"mnar_robustness_required": True}},
        },
    }


@pytest.fixture
def zenou_world():
    return build_zenou_world()


@pytest.fixture
def u6_config():
    return {
        "p_levels": ("p01", "p05"),
        "mnar_missing_threshold": 0.20,
        "source_snapshot_merkle": "snap:aaa",
        "config_sha": "cfg_u6",
        "rule_version": "redlines_v4_signed_2026-07-05",
        "stars_set_hash": "ssh_1",
    }


def make_inputs(world):
    """dict world -> m7b_assemble.inputs.U6Inputs (test convenience)."""
    from m7b_assemble.inputs import U6Inputs

    return U6Inputs(**world)


@pytest.fixture
def zenou_inputs(zenou_world):
    return make_inputs(zenou_world)
