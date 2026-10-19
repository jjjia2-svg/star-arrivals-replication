import hashlib, json, pathlib, sys
REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tools.freeze_expected import EXPECTED

EXP = REPO / "analysis" / "expected"

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def test_all_expected_present_and_hashed():
    man = dict(line.split("  ", 1)[::-1] for line in (EXP / "MANIFEST.sha256").read_text().splitlines() if line.strip())
    assert len(EXPECTED) == 29   # 23 caliber cells (2026-08-28) + 6 Panel 3 cut cells (2026-08-30, registered 2026-09-10)
    for dest, _src in EXPECTED:
        f = EXP / dest
        assert f.exists(), dest
        assert man[dest] == sha(f), dest

def test_expected_json_are_ok():
    for dest, _ in EXPECTED:
        j = json.loads((EXP / dest).read_text())
        if "channels" in j:                       # P1 family
            assert all(c["status"] == "OK" for c in j["channels"].values()), dest
        elif "status" in j:
            assert j["status"] == "OK", dest
        elif "pair_cluster" in j:                  # P3lb A_far family
            assert j["pair_cluster"]["ate"] is not None, dest
            assert j["event_cluster"]["ate"] is not None, dest
            assert len(j["pair_cluster"]["effects"]) == 5, dest
        else:
            assert False, f"{dest}: unknown result shape"

def test_freeze_expected_writes_the_committed_sources_text(tmp_path, monkeypatch):
    """freeze_expected.py rewrites SOURCES.md and MANIFEST.sha256 whenever it runs (promote.py calls it),
    so it must write the committed text, or a re-run silently undoes it."""
    import tools.freeze_expected as fe
    monkeypatch.setattr(fe, "load_paths", lambda: {"expected": tmp_path, "repo_root": REPO,
                                                   "legacy_v2_output": tmp_path / "no_legacy_tree"})
    fe.main()
    assert (tmp_path / "SOURCES.md").read_text(encoding="utf-8") == (EXP / "SOURCES.md").read_text(encoding="utf-8")
    assert (tmp_path / "MANIFEST.sha256").read_bytes() == (EXP / "MANIFEST.sha256").read_bytes()
