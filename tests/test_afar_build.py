import hashlib, pathlib, sys, pytest
REPO = pathlib.Path(__file__).resolve().parents[1]; sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths
import analysis.robustness.p3_afar.build_afar as _ba
from analysis.robustness.p3_afar.build_afar import build_afar, SOURCES
from pipeline.frames.make_slim import content_equal
P = load_paths()

# 2026-09-23: data/frames/ was promoted to the October caliber (cal2026-10 — data/frames/README.md, first
# canon paragraph). build_afar.py is the M1 one-cell port whose proof is the 2026-08-28 caliber (its SOURCES
# still read the 08-28 pair tables), so the chem/math rebuilds are compared with the 2026-08-28 frames,
# frozen byte for byte at data/cal2026-08-28/frames/ (tag cal-2026-08-28), with the 08-28 copies of the two
# frames SOURCES resolves in data/frames/ as P1/P2 inputs (same names, that directory). The builder is
# untouched — only its source map is re-pointed for this test.
CAL = P["repo_root"] / "data" / "cal2026-08-28" / "frames"
#: The econ pairs table is not shipped and is staged at output/cal_intermediates/pairs_unified.csv by BOTH
#: calibers' chains, so the file there is identified by sha256 and proven against ITS OWN canon, never mixed:
#:   08-28  41d9f7e3… — data/cal2026-08-28/frames/staging_manifest_2026-08-28.json, entry
#:                      econ_fnfix_2026-08-15/data/pairs_unified.csv (origin cal-stage:p2-econ)
#:                      -> P1/P2 from data/cal2026-08-28/frames/, compared with the 08-28 A_far frame there;
#:   October e5c98b84… — data/cal2026-10/frames/assembly_2026-10.json `pairs_unified_econ` (staged_to)
#:                      -> P1/P2 = the shipped SOURCES (data/frames/), compared with data/frames/p3_afar_econ.
#: An unidentified table at that path is an error, not a skip; an absent one skips as before.
PAIRS_ECON = {"41d9f7e3fd5ae60165589ed9848a4bfb0d2dea80df35a1c87dcc310dc596b7de": "cal2026-08-28",
              "e5c98b848882523a9b48f7cd39edb9c67bf79214f8bd600e95044b6c42abd10a": "cal2026-10"}
#: A_far pairs / ties per canon: data/cal2026-08-28/frames/p3_afar_counts.csv (the 2026-08-28 build; pre-caliber
#: was 23,831/1,077, 2,385/258, 2,689/101) and data/frames/p3_afar_counts.csv (the October sweep,
#: pipeline/frames/cal2026-10/run_cal_afar.py; the port reproduces its econ cell too — pinned below)
COUNTS = {"cal2026-08-28": {"econ": (23758, 1074), "chemistry": (2466, 266), "math_stats": (2770, 106)},
          "cal2026-10": {"econ": (24110, 1052)}}


def _sources_0828(p):
    src = SOURCES(p)
    for f, s in src.items():
        s["frame"], s["p2"] = CAL / f"p1_frame_{f}.csv", CAL / f"p2_becoming_{f}.csv"
    return src


def _canon(field: str, pairs: pathlib.Path) -> str:
    if not pairs.exists(): pytest.skip("cal pair table not available on this machine (econ pairs_unified is regenerable, not shipped)")
    if field != "econ":
        return "cal2026-08-28"
    got = hashlib.sha256(pairs.read_bytes()).hexdigest()
    assert got in PAIRS_ECON, f"{pairs} is neither caliber's econ pairs table (sha256 {got}); see PAIRS_ECON"
    return PAIRS_ECON[got]


@pytest.mark.parametrize("field", ["math_stats", "chemistry", "econ"])
def test_afar_rebuild_equals_frozen(field, tmp_path, monkeypatch):
    # Since the 2026-08-28 freeze SOURCES points at the CAL pair tables: chem/math are shipped
    # (data/cal2026-08-28/frames/pairs_none_*.parquet); the econ cal pairs_unified.csv (663 MB) is not shipped
    # and regenerates in ~24 s via the caliber chain (see build_afar.SOURCES) — absent, the econ case skips.
    src = SOURCES(P)[field]
    assert src["pairs"] == (P["repo_root"] / "output/cal_intermediates/pairs_unified.csv" if field == "econ"
                            else CAL / f"pairs_none_{field}.parquet")      # the shipped builder reads the 08-28 tables
    canon = _canon(field, src["pairs"])
    if canon == "cal2026-08-28":
        monkeypatch.setattr(_ba, "SOURCES", _sources_0828)                # 08-28 P1/P2 in, 08-28 frame out
        frozen = CAL / f"p3_afar_{field}.parquet"
    else:                                                                 # October table: shipped SOURCES = October P1/P2
        frozen = P["frames"] / f"p3_afar_{field}.parquet"
    stats = build_afar(field, out_dir=tmp_path)
    assert content_equal(tmp_path / f"p3_afar_{field}.parquet", frozen, cols=("grp","ev","year","y","D"))
    assert (stats["pairs"], stats["ties"]) == COUNTS[canon][field]
