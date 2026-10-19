import hashlib, pathlib, sys, pytest
REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths
from pipeline.frames.make_slim import make_slim, content_equal

# Since the 2026-08-28 freeze the frozen slims are the caliber rebuild, so the sources are the CAL
# pair tables: chem/math are shipped in data/cal2026-08-28/frames/; the econ cal pairs_unified.csv
# (663 MB) is not shipped — it regenerates in ~24 s via the caliber chain (run_cal_frames p2-econ;
# sha pinned in the frames run report) at output/cal_intermediates/, and the econ case skips when
# it is absent. (The full slim proof runs inside tests/test_pipeline_rebuild.py's caliber chain.)
# 2026-09-23: data/frames/ was promoted to the October caliber (cal2026-10 — data/frames/README.md, first
# canon paragraph). The chem/math builds feed the 08-28 pair tables, so they are compared with the 08-28
# slims, frozen byte for byte at data/cal2026-08-28/frames/ (tag cal-2026-08-28). The econ staging path is
# shared by both calibers' chains, so the table there is identified by sha256 and compared with ITS OWN
# canon (08-28 -> data/cal2026-08-28/frames/, October -> data/frames/), never mixed; an unidentified table is
# an error, an absent one skips as before.
P = load_paths(); CAL = P["repo_root"] / "data" / "cal2026-08-28" / "frames"
SRC = {"econ": P["repo_root"] / "output/cal_intermediates/pairs_unified.csv",
       "chemistry": CAL / "pairs_none_chemistry.parquet",
       "math_stats": CAL / "pairs_none_math_stats.parquet"}
#: 08-28: data/cal2026-08-28/frames/staging_manifest_2026-08-28.json (entry econ_fnfix_2026-08-15/data/pairs_unified.csv);
#: October: data/cal2026-10/frames/assembly_2026-10.json `pairs_unified_econ` (the table the October slims were made from)
PAIRS_ECON = {"41d9f7e3fd5ae60165589ed9848a4bfb0d2dea80df35a1c87dcc310dc596b7de": CAL,
              "e5c98b848882523a9b48f7cd39edb9c67bf79214f8bd600e95044b6c42abd10a": P["frames"]}

@pytest.mark.parametrize("field", ["math_stats", "chemistry", "econ"])
def test_make_slim_matches_frozen_slims(field, tmp_path):
    if not SRC[field].exists(): pytest.skip("cal pair table not available on this machine (econ pairs_unified is regenerable, not shipped)")
    frozen_dir = CAL
    if field == "econ":
        got = hashlib.sha256(SRC[field].read_bytes()).hexdigest()
        assert got in PAIRS_ECON, f"{SRC[field]} is neither caliber's econ pairs table (sha256 {got}); see PAIRS_ECON"
        frozen_dir = PAIRS_ECON[got]
    out = tmp_path / f"slim_{field}.parquet"
    stats = make_slim(field, SRC[field], out)
    assert stats["rows"] > 0
    assert content_equal(out, frozen_dir / f"p3_slim_{field}.parquet")                       # bytes shipped to EC2 / used locally
    assert content_equal(out, frozen_dir / f"p3_slim_ev_{field}.parquet", cols=("grp","ev","year","y","D"))

def test_content_equal_detects_difference(tmp_path):
    import duckdb
    a = tmp_path / "a.parquet"; b = tmp_path / "b.parquet"
    duckdb.sql("SELECT 1 AS grp, 2000 AS year, 0 AS y, 0 AS D").write_parquet(str(a))
    duckdb.sql("SELECT 1 AS grp, 2000 AS year, 1 AS y, 0 AS D").write_parquet(str(b))
    assert not content_equal(a, b)
