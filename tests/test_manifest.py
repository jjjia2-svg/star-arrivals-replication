import pathlib, subprocess, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tools.import_frozen import FROZEN

def test_manifest_verifies():
    r = subprocess.run([sys.executable, str(REPO / "tools/verify_manifest.py")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_every_frozen_file_present_and_small():
    for dest, _ in FROZEN:
        f = REPO / dest
        assert f.exists(), dest
        assert f.stat().st_size < 100 * 1024 * 1024, f"{dest} too large for git"

def test_canonical_frames_exist():
    for name in ["p1_frame_econ.csv", "p1_frame_chemistry.csv", "p1_frame_math_stats.csv",
                 "p2_becoming_econ.csv", "p2_becoming_chemistry.csv", "p2_becoming_math_stats.csv",
                 "p3_slim_econ.parquet", "p3_slim_chemistry.parquet", "p3_slim_math_stats.parquet",
                 "p3_slim_ev_econ.parquet", "p3_slim_ev_chemistry.parquet", "p3_slim_ev_math_stats.parquet",
                 "p3_afar_econ.parquet", "p3_afar_chemistry.parquet", "p3_afar_math_stats.parquet"]:
        assert (REPO / "data/frames" / name).exists(), name
