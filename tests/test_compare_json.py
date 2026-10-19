import json, pathlib, subprocess, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.compare_json import compare

def test_equal_ignoring_secs_and_file():
    a = {"ate": -0.371, "secs": 10.0, "file": "x.csv", "effects": [{"k": 1, "est": 0.1}]}
    b = {"ate": -0.371, "secs": 99.0, "file": "y.csv", "effects": [{"k": 1, "est": 0.1}]}
    assert compare(a, b) == []

def test_reports_numeric_difference_exactly():
    a = {"channels": {"union": {"ate": -0.37100001}}}
    b = {"channels": {"union": {"ate": -0.371}}}
    d = compare(a, b)
    assert d and d[0].startswith("channels.union.ate")

def test_reports_missing_key_and_list_length():
    assert compare({"a": 1}, {"a": 1, "b": 2}) == ["b: missing in new"]
    assert compare({"e": [1, 2]}, {"e": [1]}) == ["e: list length 2 != 1"]

def test_cli(tmp_path):
    n = tmp_path / "n.json"; e = tmp_path / "e.json"
    n.write_text(json.dumps({"ate": 1, "secs": 1})); e.write_text(json.dumps({"ate": 1, "secs": 2}))
    r = subprocess.run([sys.executable, "-m", "analysis.lib.compare_json", str(n), str(e)], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    e.write_text(json.dumps({"ate": 2}))
    r = subprocess.run([sys.executable, "-m", "analysis.lib.compare_json", str(n), str(e)], cwd=REPO, capture_output=True, text=True)
    assert r.returncode == 1 and "ate" in r.stdout
