# -*- coding: utf-8 -*-
"""The paper readers take their roots from config only (small runner).

analysis/lib/canon.py decides October vs an M canon from the paths config in force; tools/r1_canon.py
writes and checks an M canon's MANIFESTs against analysis/lib/canon_reads.tsv. These tests build tiny
canons in tmp; nothing under the October roots is written. The generator-level proofs (byte equality
with the code before the canon module, an October copy read as M, the audited reads) are in
tests/test_r1_canon_generators.py (big host).
"""
from __future__ import annotations

import fnmatch
import importlib.util
import io
import json
import pathlib
import re
import subprocess
import sys
import tokenize

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib import canon  # noqa: E402
from analysis.lib.paths import load_paths  # noqa: E402

TOOL = REPO / "tools" / "r1_canon.py"
_spec = importlib.util.spec_from_file_location("r1_canon_tool", TOOL)
r1c = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(r1c)   # type: ignore[union-attr]

COUNTS = {"schema": "sar.r1.counts.v1", "config": "M", "events": {"econ": 2, "chemistry": 1, "math_stats": 1},
          "events_total": 4, "candidates": 5}


def _yaml(tmp_path, moved: dict, name="paths.yaml") -> pathlib.Path:
    """The paths config in force, written absolute, with `moved` keys replaced."""
    cfg = {k: str(v) for k, v in load_paths().items()}
    cfg["repo_root"] = "."
    cfg.update({k: str(v) for k, v in moved.items()})
    p = tmp_path / name
    p.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


def _tiny_canon(tmp_path, switches=None, with_json=True) -> pathlib.Path:
    root = tmp_path / "canon"
    for k in canon.KEYS:
        (root / k).mkdir(parents=True, exist_ok=True)
    if with_json:
        (root / "CANON.json").write_text(json.dumps(
            {"schema": "sar.r1.canon.v1", "canon": "M", "prefix": {k: k for k in canon.KEYS},
             "switches": dict(switches or {})}), encoding="utf-8")
    return root


def _use_m(tmp_path, monkeypatch, root) -> None:
    cfg = _yaml(tmp_path, {k: root / k for k in canon.KEYS}, "paths_m.yaml")
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(cfg))


def test_default_config_is_m():
    # The test plugin selects October; the shipped default is checked explicitly.
    P = load_paths(REPO / "config" / "paths.yaml")
    assert canon.mode(P) == "M"
    for key in canon.KEYS:
        assert canon.root(key, P) == (REPO / "data" / "report" / key).resolve()
    assert canon.counts(P)["events"] == {"econ": 173, "chemistry": 97, "math_stats": 107}
    assert canon.switch("p_full_precision", P) is True


def test_test_config_keeps_october_mode():
    P = load_paths()
    assert canon.mode() == "october"
    assert P["cal"] == REPO / "data" / "cal2026-10"
    assert P["paper_inputs"] == REPO / "data" / "paper_inputs"
    assert P["cal_intermediates"] == REPO / "output" / "cal_intermediates" / "cal2026-10"
    assert canon.root("expected") == (REPO / "analysis" / "expected").resolve()
    assert canon.switch("p_full_precision") is False and canon.switch("anything") is False
    assert canon.counts()["events"] == {"econ": 113, "chemistry": 38, "math_stats": 33}


def test_paths_aws_m_moves_exactly_the_six_canon_keys():
    aws = yaml.safe_load((REPO / "config" / "r1" / "paths_aws.yaml").read_text(encoding="utf-8"))
    m = yaml.safe_load((REPO / "config" / "r1" / "paths_aws_m.yaml").read_text(encoding="utf-8"))
    assert set(m) == set(aws), set(m) ^ set(aws)
    for k in aws:
        assert m[k] == (f"/work/canon_m/{k}" if k in canon.KEYS else aws[k]), k


def test_write_paths_yaml_quotes_every_value_for_r(tmp_path):
    """copy-october --paths-out once wrote `repo_root: .` plain (yaml.safe_dump). R's yaml package
    (analysis/lib/paths.R) types a plain '.' with the YAML 1.1 float pattern and read NA ('. is not a
    real'), so sar_paths() stopped at `if (startsWith(v, "/"))` and every R paper generator failed under
    the M copy. Every value is now a double-quoted scalar, as config/paths.yaml writes repo_root: a
    string to every YAML reader, and Python reads the same keys and values."""
    out = r1c.write_paths_yaml(tmp_path / "canon", tmp_path / "paths_m.yaml", output=tmp_path / "out")
    text = out.read_text(encoding="utf-8")
    assert [k.value for k, v in yaml.compose(text).value if v.style != '"'] == [], text
    d = yaml.safe_load(text)
    assert d["repo_root"] == "." and all(isinstance(v, str) for v in d.values()), d
    assert all(d[k] == str((tmp_path / "canon" / k).resolve()) for k in canon.KEYS), d
    assert d["output"] == str((tmp_path / "out").resolve()) and set(d) == set(load_paths()), d
    # the plain form is the R failure: '.' matches YAML 1.1's float pattern (yaml.org/type/float.html)
    assert re.fullmatch(r"[-+]?([0-9][0-9_]*)?\.[0-9.]*([eE][-+][0-9]+)?", ".")


def test_mixed_roots_are_refused(tmp_path, monkeypatch):
    (tmp_path / "cal").mkdir()
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(_yaml(tmp_path, {"cal": tmp_path / "cal"})))
    with pytest.raises(canon.CanonError, match="mixed"):
        canon.mode()
    # and the other way round: everything moved but frames
    root = _tiny_canon(tmp_path)
    moved = {k: root / k for k in canon.KEYS if k != "frames"}
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(_yaml(tmp_path, moved, "p2.yaml")))
    with pytest.raises(canon.CanonError, match="mixed"):
        canon.key(root / "cal" / "x.csv")


def test_missing_canon_keys_are_named_in_plain_words(tmp_path):
    P = {"repo_root": tmp_path, "cal": tmp_path / "cal", "frames": tmp_path / "frames"}
    with pytest.raises(canon.CanonError) as e:
        canon.state(P)
    missing = [k for k in canon.KEYS if k not in P]
    assert str(e.value).endswith(f"lacks the canon keys {missing}; config/paths.yaml lists all six"), e.value


def test_m_root_needs_canon_json_and_declared_switches(tmp_path, monkeypatch):
    root = _tiny_canon(tmp_path, with_json=False)
    _use_m(tmp_path, monkeypatch, root)
    with pytest.raises(canon.CanonError, match="CANON.json"):
        canon.mode()
    (root / "CANON.json").write_text(json.dumps({"schema": "sar.r1.canon.v1", "canon": "M",
                                                 "prefix": {"cal": "cal"}, "switches": {}}))
    with pytest.raises(canon.CanonError, match="sar.r1.canon.v1"):
        canon.mode()
    (root / "CANON.json").unlink()
    _tiny_canon(tmp_path, switches={"p_full_precision": True, "other": False})
    assert canon.mode() == "M"
    assert canon.switch("p_full_precision") is True and canon.switch("other") is False
    with pytest.raises(canon.CanonError, match="not declared"):
        canon.switch("undeclared_switch")
    with pytest.raises(canon.CanonError, match="counts"):
        canon.counts()
    (root / "cal" / "counts.json").write_text(json.dumps(COUNTS))
    assert canon.counts()["events"]["econ"] == 2
    (root / "cal" / "counts.json").write_text(json.dumps({**COUNTS, "events_total": 9}))
    with pytest.raises(canon.CanonError, match="sar.r1.counts.v1"):
        canon.counts()


def test_key_is_repo_relative_in_october_and_prefix_relative_in_m(tmp_path, monkeypatch):
    P = load_paths()
    ev = P["cal"] / "events_econ_cal2026-10.csv"
    assert canon.key(ev) == "data/cal2026-10/events_econ_cal2026-10.csv"
    assert canon.key(P["expected"] / "P1_econ_fnfix.json") == "analysis/expected/P1_econ_fnfix.json"
    assert canon.key(P["cal_intermediates"] / "pairs_unified.csv") == "output/cal_intermediates/cal2026-10/pairs_unified.csv"
    assert canon.resolve("data/cal2026-10/events_econ_cal2026-10.csv") == REPO / "data/cal2026-10/events_econ_cal2026-10.csv"
    assert canon.manifest("cal") == REPO / "data" / "cal2026-10" / "MANIFEST.sha256"
    assert canon.manifest("frames") == REPO / "data" / "MANIFEST.sha256"
    assert canon.freeze_manifest(P["cal"] / "robustness" / "battery") == \
        P["cal"] / "robustness" / "battery" / "MANIFEST.sha256"
    assert canon.pinned(ev) == ev          # the October MANIFEST pins it

    root = _tiny_canon(tmp_path).resolve()
    _use_m(tmp_path, monkeypatch, root)
    f = root / "cal" / "robustness" / "battery" / "x.csv"
    assert canon.mode() == "M"
    assert canon.key(f) == "cal/robustness/battery/x.csv"
    assert canon.key(root / "expected" / "P1_econ_fnfix.json") == "expected/P1_econ_fnfix.json"
    assert canon.key(REPO / "pipeline" / "README.md") == "pipeline/README.md"   # a repo file outside the canon
    assert canon.resolve("cal/robustness/battery/x.csv") == f
    assert canon.resolve("data/cal2026-10/robustness/battery/x.csv") == f       # as an October report records it
    assert canon.manifest("frames") == root / "frames" / "MANIFEST.sha256"
    assert canon.freeze_manifest(f.parent) == root / "cal" / "MANIFEST.sha256"
    assert canon.kind_of(root / "cal_intermediates" / "pairs_unified.csv") == "cal_intermediates"
    with pytest.raises(canon.CanonError):
        canon.key(tmp_path / "elsewhere.csv")


def _write_tsv(path, rows):
    path.write_text("# test rows\ngenerator\tkey\trel\tkind\treason\n"
                    + "".join("\t".join(r) + "\n" for r in rows), encoding="utf-8")
    return path


def _r1_canon(*args):
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True, cwd=REPO)


def test_manifest_check_round_trip_and_one_byte_off(tmp_path, monkeypatch):
    root = _tiny_canon(tmp_path)
    (root / "cal" / "sub").mkdir()
    (root / "cal" / "sub" / "a.csv").write_text("x,y\n1,2\n")
    (root / "cal" / "s_1.csv").write_text("1\n")
    (root / "cal" / "s_2.csv").write_text("2\n")
    (root / "frames" / "b.csv").write_text("b\n")
    tsv = _write_tsv(tmp_path / "reads.tsv", [
        ("g.py", "cal", "sub/a.csv", "product", "r"),
        ("g.py", "cal", "s_*.csv", "product", "r"),
        ("g.py", "frames", "b.csv", "carried", "r"),
        ("g.py", "paper_inputs", "maybe.json", "optional", "r"),          # absent, allowed
        ("g.py", "legacy_v2_output", "anything/at/all.csv", "carried", "r"),   # not in the canon
    ])
    r = _r1_canon("manifest", root)
    assert r.returncode == 0, r.stderr
    man = canon.read_manifest(root / "cal" / "MANIFEST.sha256")
    assert set(man) == {"cal/sub/a.csv", "cal/s_1.csv", "cal/s_2.csv"}
    assert all(k.startswith("cal/") for k in man)                      # never a data/cal2026-10 key
    r = _r1_canon("check", root, "--tsv", tsv)
    assert r.returncode == 0 and "CANON_OK" in r.stdout, r.stdout + r.stderr

    _use_m(tmp_path, monkeypatch, root)
    assert canon.pinned(root / "cal" / "sub" / "a.csv") == root / "cal" / "sub" / "a.csv"

    b = bytearray((root / "cal" / "sub" / "a.csv").read_bytes()); b[0] ^= 1
    (root / "cal" / "sub" / "a.csv").write_bytes(bytes(b))
    r = _r1_canon("check", root, "--tsv", tsv)
    assert r.returncode == 1 and "CANON_FAIL cal/sub/a.csv" in r.stdout, r.stdout
    with pytest.raises(canon.CanonError, match="sha256"):
        canon.pinned(root / "cal" / "sub" / "a.csv")

    _r1_canon("manifest", root)
    (root / "frames" / "b.csv").unlink()
    with open(root / "cal" / "MANIFEST.sha256", "a") as fh:
        fh.write("0" * 64 + "  data/cal2026-10/sub/a.csv\n")
    r = _r1_canon("check", root, "--tsv", tsv)
    assert r.returncode == 1, r.stdout
    assert "CANON_FAIL frames/b.csv: missing" in r.stdout and "outside 'cal/'" in r.stdout, r.stdout


def test_canon_reads_tsv_is_well_formed_and_matches_october():
    rows = r1c.read_tsv()
    P = load_paths()
    assert rows and {r["kind"] for r in rows} <= {"product", "carried", "optional"}
    for r in rows:
        gen = r["generator"]
        assert (REPO / "analysis" / "paper" / gen).is_file() or (REPO / "tools" / gen).is_file(), gen
        assert r["key"] in P or r["key"] == "canon_root", r     # canon_root: beside the six key folders
        if r["key"] not in canon.KEYS:
            continue
        base = canon.october_path(r["key"])
        if r["key"] == "cal_intermediates" and not base.is_dir():
            continue          # git-ignored; rebuilt on AWS
        if (r["key"], r["rel"]) == ("cal", canon.COUNTS):
            continue          # M only: October's counts are config/r1/counts_B0.json (copy-october writes it)
        hits = [p for p in base.rglob("*") if p.is_file()
                and fnmatch.fnmatchcase(p.relative_to(base).as_posix(), r["rel"])]
        assert hits, f"no October file for {r['key']}/{r['rel']} ({gen})"


# ---- the October roots are spelled in one place only ------------------------------------------------
_OCT_DIRS = {"cal2026-10", "paper_inputs", "cal_intermediates", "raw_verified"}
_OCT_PREFIX = ("data/cal2026-10", "analysis/expected", "data/paper_inputs", "data/frames/",
               "data/raw_verified/", "output/cal_intermediates")
_JOINS = {("data", "frames"), ("data", "raw_verified"), ("data", "paper_inputs"), ("data", "cal2026-10"),
          ("analysis", "expected"), ("output", "cal_intermediates")}


def _strings(src: str):
    """(line, value, previous significant token, the two tokens before it) for every string in code -
    docstrings and comments excluded; an f-string yields its leading literal part."""
    toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
            if t.type not in (tokenize.COMMENT, tokenize.NL)]
    fs_start = getattr(tokenize, "FSTRING_START", None)
    fs_mid = getattr(tokenize, "FSTRING_MIDDLE", None)
    for i, t in enumerate(toks):
        prev = toks[i - 1] if i else None
        if t.type == tokenize.STRING:
            nxt = toks[i + 1] if i + 1 < len(toks) else None
            if (prev is None or prev.type in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                                              tokenize.ENCODING)) \
                    and (nxt is None or nxt.type in (tokenize.NEWLINE, tokenize.ENDMARKER)):
                continue                                   # a docstring / bare string statement
            m = re.match(r"^([A-Za-z]*)('''|\"\"\"|'|\")", t.string)
            val = t.string[m.end():len(t.string) - len(m.group(2))]
            if "f" in m.group(1).lower():
                val = val.split("{", 1)[0]                 # an f-string (Python < 3.12): its literal head
            yield t.start[0], val, prev, toks[i - 2] if i >= 2 else None
        elif fs_mid is not None and t.type == fs_mid and prev is not None and prev.type == fs_start:
            yield t.start[0], t.string, toks[i - 2] if i >= 2 else None, None


def october_root_literals(src: str) -> list:
    hits = []
    for line, val, prev, before in _strings(src):
        if val.startswith(_OCT_PREFIX) and not re.search(r"\s", val):
            hits.append((line, val))         # a path; a sentence that names a path is a description
        elif prev is not None and prev.string == "/" and val in _OCT_DIRS:
            hits.append((line, val))
        elif prev is not None and prev.string == "/" and before is not None and before.type == tokenize.STRING \
                and (before.string.strip("'\""), val) in _JOINS:
            hits.append((line, val))
    return hits


def test_the_october_root_scan_catches_a_planted_root():
    planted = ('"""data/cal2026-10/in a docstring is fine"""\n'
               'import x  # data/cal2026-10 in a comment is fine\n'
               'A = P["repo_root"] / "data" / "cal2026-10"\n'
               'B = "data/cal2026-10/events_econ_cal2026-10.csv"\n'
               'C = ROOT / "analysis/expected"\n'
               'D = P["repo_root"] / "data" / "frames"\n'
               'E = f"data/cal2026-10/events_{f}.csv"\n'
               'F = P["cal"] / "events_econ_cal2026-10.csv"\n'
               'G = "note: read from data/cal2026-10/x (a description, not a path)"\n'
               'H = "data/frames p1_frame/p2_becoming row counts (a description)"\n')
    got = {line for line, _ in october_root_literals(planted)}
    assert got == {3, 4, 5, 6, 7}, october_root_literals(planted)


def test_no_reader_builds_the_october_root():
    files = sorted((REPO / "analysis" / "paper").glob("*.py")) + [REPO / "tools" / "compare_all.py"]
    bad = {f.relative_to(REPO).as_posix(): h for f in files
           if (h := october_root_literals(f.read_text(encoding="utf-8")))}
    assert not bad, bad
    # the R generators take every root from paths.R (p$frames / p$expected / p$output)
    for f in sorted((REPO / "analysis" / "paper").glob("*.R")):
        code = "\n".join(ln.split("#", 1)[0] for ln in f.read_text(encoding="utf-8").splitlines())
        lits = re.findall(r"\"([^\"]*)\"|'([^']*)'", code)
        assert not [a or b for a, b in lits if re.search(r"data/|analysis/expected|cal2026-10", a or b)], f.name


def test_compare_all_default_argv_unchanged(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("compare_all", REPO / "tools" / "compare_all.py")
    calls = []

    def fake_run(argv, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "CUSTODY_OK\n", "")

    def run(*args):
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)   # type: ignore[union-attr]
        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        rc = mod.main(list(args))
        return rc, calls.pop()

    out = tmp_path / "out"
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(_yaml(tmp_path, {"output": out})))
    rc, argv = run()
    assert argv == [sys.executable, str(REPO / "tools" / "verify_cloud_custody.py"), "--custody", "data/cal2026-10/cloud"]
    assert (out / "compare_report.md").is_file() and (out / "logs" / "custody.log").read_text() == "CUSTODY_OK\n"
    rc, argv = run("--custody-spec", str(tmp_path / "spec.json"))
    assert argv[-4:] == ["--custody", "data/cal2026-10/cloud", "--spec", str(tmp_path / "spec.json")]

    # a canon tree: its own custody folder and record (not cal/cloud, the robustness batch); absolute outside the repo
    root = _tiny_canon(tmp_path).resolve()
    cfg = _yaml(tmp_path, {**{k: root / k for k in canon.KEYS}, "output": out}, "paths_m.yaml")
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(cfg))
    rc, argv = run()
    assert argv[2:] == ["--custody", str(root / "custody"), "--spec", str(root / "custody" / "custody_r1.json")]
    rc, argv = run("--custody-spec", str(tmp_path / "spec.json"))
    assert argv[2:] == ["--custody", str(root / "custody"), "--spec", str(tmp_path / "spec.json")]


def test_canon_reads_names_the_custody_record_compare_all_reads():
    rows = [r for r in r1c.read_tsv() if r["generator"] == "compare_all.py"]
    assert {(r["key"], r["rel"]) for r in rows} == {("expected", "*.json"), ("canon_root", "custody/custody_r1.json")}


def test_compare_all_custody_checks_only_the_rcloud_rows(tmp_path, monkeypatch):
    """A gold with no result is VERIFIED_NOT_RERUN only when its cell list row is rcloud and custody passed."""
    spec = importlib.util.spec_from_file_location("compare_all", REPO / "tools" / "compare_all.py")
    root = _tiny_canon(tmp_path).resolve()
    for g in ("P3_econ_fnfix.json", "P3evcl_chemistry.json", "P1_econ_fnfix.json"):
        (root / "expected" / g).write_text('{"label": "x"}\n', encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setenv("SAR_PATHS_CONFIG", str(_yaml(tmp_path, {**{k: root / k for k in canon.KEYS}, "output": out},
                                                     "paths_m.yaml")))
    for custody_rc, want in ((0, {"P3_econ_fnfix.json": "VERIFIED_NOT_RERUN", "P3evcl_chemistry.json": "VERIFIED_NOT_RERUN",
                                  "P1_econ_fnfix.json": "MISSING"}),
                             (1, {"P3_econ_fnfix.json": "MISSING", "P3evcl_chemistry.json": "MISSING",
                                  "P1_econ_fnfix.json": "MISSING"})):
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)   # type: ignore[union-attr]
        monkeypatch.setattr(mod.subprocess, "run",
                            lambda argv, rc=custody_rc, **kw: subprocess.CompletedProcess(argv, rc, "", ""))
        assert mod.main([]) == 1
        rep = (out / "compare_report.md").read_text(encoding="utf-8")
        got = dict(re.findall(r"^\| (\S+\.json) \| (\S+) \|", rep, re.M))
        assert got == want, got


# ---- where an M canon may live ----------------------------------------------------------------------
def _canon_at(root: pathlib.Path, prefix=None) -> pathlib.Path:
    """A tiny M canon at `root`: CANON.json and one directory per key."""
    prefix = prefix or {k: k for k in canon.KEYS}
    for k in canon.KEYS:
        (root / prefix[k]).mkdir(parents=True, exist_ok=True)
    (root / "CANON.json").write_text(json.dumps(
        {"schema": "sar.r1.canon.v1", "canon": "M", "prefix": prefix, "switches": {}}), encoding="utf-8")
    return root


def _p_for(repo: pathlib.Path, root: pathlib.Path, prefix=None) -> dict:
    """A paths dict for the clone `repo` with the six canon keys under `root`."""
    prefix = prefix or {k: k for k in canon.KEYS}
    return {"repo_root": repo, **{k: root / prefix[k] for k in canon.KEYS}}


def test_m_canon_under_data_is_accepted(tmp_path):
    repo = (tmp_path / "clone").resolve()
    root = _canon_at(repo / "data" / "report")
    P = _p_for(repo, root)
    s = canon.state(P)
    assert s.mode == "M" and s.root == root
    assert canon.key(root / "cal" / "events.csv", P) == "cal/events.csv"     # prefix keys, as outside the clone
    assert canon.key(repo / "pipeline" / "README.md", P) == "pipeline/README.md"
    assert canon.resolve("cal/events.csv", P) == root / "cal" / "events.csv"
    assert canon.manifest("frames", P) == root / "frames" / "MANIFEST.sha256"
    deep = _canon_at(repo / "data" / "versions" / "r1")
    assert canon.mode(_p_for(repo, deep)) == "M"


def test_m_canon_elsewhere_in_the_clone_is_refused(tmp_path, monkeypatch):
    repo = (tmp_path / "clone").resolve()
    pre = {k: f"m_{k}" for k in canon.KEYS}       # no key directory is named like an October root
    for where, msg in ((repo, "not under"),                                   # the clone itself
                       (repo / "output" / "canon", "not under"),
                       (repo / "analysis" / "canon", "not under"),
                       (repo / "data", "not under"),                           # data/ itself
                       (repo / "data" / "cal2026-10", "October root"),         # equals an October root
                       (repo / "data" / "frames" / "canon", "October root"),   # lies inside one
                       (repo / "output" / "cal_intermediates" / "cal2026-10" / "c", "not under")):
        root = _canon_at(where, pre)
        with pytest.raises(canon.CanonError, match=msg):
            canon.mode(_p_for(repo, root, pre))
    # a key directory that links into an October root
    root = _canon_at(repo / "data" / "linked")
    (repo / "data" / "frames" / "sub").mkdir(parents=True)
    (root / "frames").rmdir()
    (root / "frames").symlink_to(repo / "data" / "frames" / "sub")
    with pytest.raises(canon.CanonError, match="October root"):
        canon.mode(_p_for(repo, root))
    # a canon that contains an October root
    monkeypatch.setattr(canon, "OCTOBER", {**canon.OCTOBER, "cal": "data/old/cal2026-10"})
    root = _canon_at(repo / "data" / "old", pre)
    with pytest.raises(canon.CanonError, match="October root"):
        canon.mode(_p_for(repo, root, pre))


def test_m_canon_outside_the_clone_behaves_as_before(tmp_path):
    repo = (tmp_path / "clone").resolve()
    (repo / "data").mkdir(parents=True)
    # outside the clone, October directory names do not matter
    for where in (tmp_path / "work" / "canon_m", tmp_path / "data" / "cal2026-10", tmp_path / "output"):
        root = _canon_at(where).resolve()
        P = _p_for(repo, root)
        assert canon.mode(P) == "M" and canon.state(P).root == root, where
        assert canon.key(root / "cal" / "x.csv", P) == "cal/x.csv"


def test_m_canon_sharing_an_external_october_root_is_refused(tmp_path):
    """The October cal root links outside the clone. A canon key that links into it, or a canon root
    that lies inside or contains it, is refused even when the path is outside the clone. A key that
    differs from its own October key is not caught by the mixed-roots check, so only this check stops it."""
    repo = (tmp_path / "clone").resolve()
    (repo / "data").mkdir(parents=True)
    ext = tmp_path / "archive" / "october" / "cal"
    (ext / "frames").mkdir(parents=True)
    ext = ext.resolve()
    (repo / "data" / "cal2026-10").symlink_to(ext)
    pre = {k: f"m_{k}" for k in canon.KEYS}
    # a canon under data/ whose frames key links into the external October cal
    root = _canon_at(repo / "data" / "report")
    (root / "frames").rmdir()
    (root / "frames").symlink_to(ext / "frames")
    with pytest.raises(canon.CanonError, match="October root"):
        canon.mode(_p_for(repo, root))
    # the same link from a canon outside the clone
    work = _canon_at(tmp_path / "work" / "linked")
    (work / "frames").rmdir()
    (work / "frames").symlink_to(ext / "frames")
    with pytest.raises(canon.CanonError, match="October root"):
        canon.mode(_p_for(repo, work))
    # a canon root outside the clone that lies inside, or contains, the October cal
    for where in (ext / "m", tmp_path / "archive"):
        with pytest.raises(canon.CanonError, match="October root"):
            canon.mode(_p_for(repo, _canon_at(where, pre), pre))
        with pytest.raises(canon.CanonError, match="October root"):
            canon.check_place(where, repo)
    # a canon outside the clone that shares no October subtree is accepted, as before
    clean = _canon_at(tmp_path / "work" / "canon_m").resolve()
    assert canon.mode(_p_for(repo, clean)) == "M"
    canon.check_place(tmp_path / "work" / "new", repo)


def _fake_october(repo: pathlib.Path) -> pathlib.Path:
    """A clone with one small file in each October root."""
    for k, rel in canon.OCTOBER.items():
        (repo / rel).mkdir(parents=True)
        (repo / rel / f"{k}.txt").write_text(k + "\n", encoding="utf-8")
    return repo


def test_copy_october_into_data_works_and_elsewhere_in_the_clone_is_refused(tmp_path, monkeypatch):
    repo = _fake_october((tmp_path / "clone").resolve())
    monkeypatch.setattr(r1c, "REPO", repo)
    monkeypatch.setattr(canon, "REPO_ROOT", repo)
    (tmp_path / "counts.json").write_text(json.dumps(COUNTS), encoding="utf-8")
    monkeypatch.setenv("SAR_R1_COUNTS", str(tmp_path / "counts.json"))
    dest = repo / "data" / "x"
    done = r1c.copy_october(dest)
    assert done == {k: (2 if k == "cal" else 1) for k in canon.KEYS}, done      # cal also gets counts.json
    assert canon.read_manifest(dest / "frames" / "MANIFEST.sha256") == {
        "frames/frames.txt": canon.sha256(repo / "data" / "frames" / "frames.txt")}
    assert canon.mode(_p_for(repo, dest)) == "M"
    tsv = _write_tsv(tmp_path / "reads.tsv", [("g.py", "frames", "frames.txt", "product", "r")])
    assert r1c.check(dest, tsv) == []
    for bad, msg in ((repo, "not under"), (repo / "output" / "x", "not under"), (repo / "data", "not under"),
                     (repo / "data" / "cal2026-10" / "x", "October root")):
        with pytest.raises(SystemExit, match=msg):
            r1c.copy_october(bad)
    assert not (repo / "output" / "x").exists() and not (repo / "data" / "cal2026-10" / "x").exists()
    assert r1c.copy_october(tmp_path / "canon_m") == done                     # outside the clone, as before
