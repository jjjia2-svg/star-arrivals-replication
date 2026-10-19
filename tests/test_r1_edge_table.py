# -*- coding: utf-8 -*-
"""pipeline/aws/r1/edge_table.py - R1 N2: chem/maths M reads the 11-school edge table under the 07-05 name.

Every table here is a toy built in tmp_path (pyarrow parquet, read back with an in-memory duckdb); the
real data root, derived_root of the instance and the legacy trees are never opened. The path resolvers
are probed in a subprocess because pipeline.lib.paths caches its config (lru_cache) at first use.
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import subprocess
import sys

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline" / "aws" / "r1"))
import edge_table as et   # noqa: E402

N_0705, N_11 = 2, 5          # rows per toy parquet in the 07-05 / 11-school table
FIELDS = ("chemistry", "math_stats")
GLOB_KEYS = ("edges_glob", "works_glob", "work_first_pub_glob")


def _parquet(path: pathlib.Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"work_id": [f"W{i}" for i in range(n)]}), path)


def _table(root: pathlib.Path, n: int, subtables=et.SUBTABLES) -> pathlib.Path:
    for sub in subtables:
        _parquet(root / sub / "bucket=000" / "part.parquet", n)
    (root / "_manifest").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def toy(tmp_path, monkeypatch):
    """A toy data root shaped like <ssd_root>: derived/{07-05, 11-school, other entries}, snapshot/, more."""
    monkeypatch.setenv("SAR_HOST", "ec2-r1-test")
    monkeypatch.delenv("SAR_SSD_ROOT", raising=False)
    real = tmp_path / "real" / "openalex_pipeline"
    derived = real / "derived"
    _table(derived / et.TABLE_0705, N_0705)
    target = _table(derived / et.TABLE_11, N_11)
    (derived / "u2_x").mkdir(parents=True)
    (derived / "u2_x" / "data.txt").write_text("u2\n")
    (derived / "notes.txt").write_text("a file entry\n")
    (real / "snapshot").mkdir()
    (real / "snapshot" / "manifest.json").write_text("{}\n")
    (real / "other_top").mkdir()
    # the base paths file = the real R1 instance config with only ssd_root pointed at the toy root
    text = (REPO / "config" / "r1" / "paths_aws.yaml").read_text(encoding="utf-8")
    text, n = re.subn(r"(?m)^ssd_root:.*$", "ssd_root: " + json.dumps(str(real)), text)
    assert n == 1
    base = tmp_path / "paths_base.yaml"
    base.write_text(text, encoding="utf-8")
    return {"tmp": tmp_path, "real": real, "derived": derived, "target": target, "base": base}


_PROBE = r"""
import json, pathlib, sys
repo = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(repo))
sys.path.insert(0, str(repo / "pipeline" / "frames" / "cal2026-10"))
import stage
from pipeline.lib import paths as plp
from analysis.lib.paths import load_paths
out = {f: stage.render_config(f, pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]))
       for f in ("chemistry", "math_stats")}
out["_derived_root"] = str(plp.derived_root())
out["_ssd_root"] = str(plp.ssd_root())
out["_leaf"] = plp.SSD_ROOT_LEAF
out["_load_paths_ssd_root"] = str(load_paths()["ssd_root"])
print(json.dumps(out))
"""


def _probe(toy, env_extra: dict) -> dict:
    """Render both chem/maths configs and resolve both path layers in a FRESH process under env_extra."""
    env = {k: v for k, v in os.environ.items() if k not in ("SAR_PATHS_CONFIG", "SAR_SSD_ROOT")}
    env.update(env_extra)
    r = subprocess.run([sys.executable, "-c", _PROBE, str(REPO), str(toy["tmp"] / "stage_shadow"),
                        str(toy["tmp"] / "run")], cwd=str(REPO), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def _count(glob: str) -> int:
    q = "SELECT count(*) FROM read_parquet('{}', hive_partitioning=0)".format(glob.replace("'", "''"))
    return duckdb.connect().execute(q).fetchone()[0]


def _real(p) -> str:
    return os.path.realpath(str(p))


def test_shadow_points_only_the_0705_name_at_the_target(toy):
    real, derived, target = toy["real"], toy["derived"], toy["target"]
    before = sorted(p.relative_to(real).as_posix() for p in real.rglob("*"))
    out = toy["tmp"] / "work" / "edge_table"
    mf = et.build_ssd_shadow(real, out, target)
    shadow = out / "openalex_pipeline"
    assert mf["shadow_ssd_root"] == str(shadow)
    assert mf["swapped_name"] == et.TABLE_0705
    assert mf["target_realpath"] == _real(target)
    assert mf["target_subtables"] == sorted(et.SUBTABLES)
    # the one swap
    assert _real(shadow / "derived" / et.TABLE_0705) == _real(target)
    # every other derived entry, and every top-level entry, resolves to the real one
    for name in sorted(os.listdir(derived)):
        if name != et.TABLE_0705:
            assert _real(shadow / "derived" / name) == _real(derived / name), name
    for name in sorted(os.listdir(real)):
        if name != "derived":
            assert (shadow / name).is_symlink() and _real(shadow / name) == _real(real / name), name
    assert (shadow / "derived").is_dir() and not (shadow / "derived").is_symlink()
    assert sorted(os.listdir(shadow / "derived")) == sorted(os.listdir(derived))
    assert sorted(os.listdir(shadow)) == sorted(os.listdir(real))
    # the manifest names every entry and sits next to the shadow root
    names = {e["name"] for e in mf["entries"]}
    assert names == ({f"derived/{n}" for n in os.listdir(derived)} | {n for n in os.listdir(real) if n != "derived"})
    swapped = [e for e in mf["entries"] if e["name"] == f"derived/{et.TABLE_0705}"]
    assert swapped == [{"name": f"derived/{et.TABLE_0705}", "link": str(target), "realpath": _real(target)}]
    assert json.loads((out / et.MANIFEST_NAME).read_text(encoding="utf-8")) == mf
    # the real tree is untouched
    assert sorted(p.relative_to(real).as_posix() for p in real.rglob("*")) == before
    # a second build over an existing shadow is refused, never merged
    with pytest.raises(FileExistsError):
        et.build_ssd_shadow(real, out, target)


def test_shadow_root_is_accepted_by_both_path_resolvers(toy):
    env = et.env_for(et.TABLE_11, real_ssd_root=toy["real"], work_dir=toy["tmp"] / "work",
                     base_paths=toy["base"])
    shadow = toy["tmp"] / "work" / et.WORK_SUBDIR / "openalex_pipeline"
    got = _probe(toy, env)
    assert got["_leaf"] == et.SSD_ROOT_LEAF == "openalex_pipeline"
    assert got["_ssd_root"] == str(shadow)
    assert got["_derived_root"] == str(shadow / "derived")
    assert got["_load_paths_ssd_root"] == str(shadow)
    assert _real(pathlib.Path(got["_derived_root"]) / et.TABLE_0705) == _real(toy["target"])
    assert _real(pathlib.Path(got["_ssd_root"]) / "snapshot") == _real(toy["real"] / "snapshot")


def test_off_is_no_env_change_and_the_rendered_config_is_identical(toy):
    work = toy["tmp"] / "work"
    off = et.env_for(et.TABLE_0705, real_ssd_root=toy["real"], work_dir=work, base_paths=toy["base"])
    assert off == {}
    assert not work.exists()                              # off writes nothing at all
    base_env = {"SAR_PATHS_CONFIG": str(toy["base"])}     # what B0 stages run under
    b0 = _probe(toy, base_env)
    m_off = _probe(toy, {**base_env, **off})
    assert set(b0) == set(m_off)
    for key in b0:
        assert m_off[key] == b0[key], key
    assert b0["_derived_root"] == str(toy["derived"])
    for f in FIELDS:
        assert _count(b0[f]["snapshot"]["edges_glob"]) == N_0705


def test_on_globs_resolve_to_the_11school_table_through_duckdb(toy):
    base_env = {"SAR_PATHS_CONFIG": str(toy["base"])}
    on = et.env_for(et.TABLE_11, real_ssd_root=toy["real"], work_dir=toy["tmp"] / "work",
                    base_paths=toy["base"])
    assert set(on) == {"SAR_PATHS_CONFIG"} and os.path.isabs(on["SAR_PATHS_CONFIG"])
    off_r = _probe(toy, base_env)
    on_r = _probe(toy, {**base_env, **on})
    shadow_derived = toy["tmp"] / "work" / et.WORK_SUBDIR / "openalex_pipeline" / "derived"
    for f in FIELDS:
        snap_on, snap_off = on_r[f]["snapshot"], off_r[f]["snapshot"]
        for key, sub in zip(GLOB_KEYS, ("authorship_edges", "works", "work_first_pub")):
            glob = snap_on[key]
            assert glob == f"{shadow_derived}/{et.TABLE_0705}/{sub}/**/*.parquet", (f, key)
            prefix = glob.split(f"/{sub}/")[0]
            assert _real(prefix) == _real(toy["target"]), (f, key)
            assert _count(glob) == N_11, (f, key)            # '**' resolves through the dir symlink
            assert _count(snap_off[key]) == N_0705, (f, key)
        # the full-snapshot FWCI pop is the LEGACY_V2 file, independent of the table
        assert snap_on["fwci_baseline_pop_glob"] == snap_off["fwci_baseline_pop_glob"]
        assert "${" not in json.dumps(on_r[f])
        assert set(snap_on) == set(snap_off)
        for key in snap_on:
            if key not in GLOB_KEYS:
                assert snap_on[key] == snap_off[key], (f, key)
        assert set(on_r[f]) == set(off_r[f])
        # the config's own note spells out what ${DERIVED} rendered to (configs/<field>.json, string.Template
        # renders the whole file), so with the switch on it names the shadow's derived root - that, and
        # nothing else, differs outside the snapshot globs
        note = "_cal2026_10_note"
        assert off_r[f][note].count(str(toy["derived"])) == 1 and str(shadow_derived) not in off_r[f][note], f
        assert on_r[f][note] == off_r[f][note].replace(str(toy["derived"]), str(shadow_derived)), f
        for key in on_r[f]:
            if key not in ("snapshot", note):
                assert on_r[f][key] == off_r[f][key], (f, key)


# --- the reader scan ------------------------------------------------------------------------------
_TABLE_NAMES = (et.TABLE_0705, et.TABLE_11, "u1_edges_full", "u1_full_11school")
_ABS_DATA = ("openalex_pipeline", "/Volumes/", "Extreme SSD")
_CFG_LINE = re.compile(r'^\s*"(edges_glob|works_glob|work_first_pub_glob)": "\$\{DERIVED\}/'
                       + re.escape(et.TABLE_0705) + r'/[a-z_]+/\*\*/\*\.parquet",?\s*$')


def _scan_py(rel: str):
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    parent = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent[child] = node
    readers, bad = set(), []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if isinstance(parent.get(node), ast.Expr):        # docstrings / bare strings are prose
            continue
        v = node.value
        if not any(t in v for t in _TABLE_NAMES + _ABS_DATA):
            continue
        p = parent.get(node)
        ok = (v == et.TABLE_0705 and isinstance(p, ast.BinOp) and isinstance(p.op, ast.Div)
              and p.right is node and isinstance(p.left, ast.Call) and not p.left.args
              and isinstance(p.left.func, ast.Name) and p.left.func.id == "_sar_derived_root")
        if ok:
            readers.add((rel, node.lineno))
        else:
            bad.append((rel, node.lineno, v))
    return readers, bad


def _scan_json(rel: str):
    readers, bad = set(), []
    for i, line in enumerate((REPO / rel).read_text(encoding="utf-8").splitlines(), 1):
        if not any(t in line for t in _TABLE_NAMES + _ABS_DATA):
            continue
        if _CFG_LINE.match(line):
            readers.add((rel, i))
        else:
            bad.append((rel, i, line.strip()))
    return readers, bad


def test_every_chemmath_reader_of_the_0705_table_goes_through_derived_root():
    assert set(et.READER_SCAN) >= {rel for rel, _ in et.GOLD_READERS}
    readers, bad = set(), []
    for rel in et.READER_SCAN:
        assert (REPO / rel).is_file(), rel
        r, b = (_scan_json if rel.endswith(".json") else _scan_py)(rel)
        readers |= r
        bad += b
    assert bad == [], f"a chem/maths reader names an edge table or a data path outside derived_root: {bad}"
    assert readers == set(et.GOLD_READERS)
    # the three gold builders and the two configs each read it; the chem/maths drivers never name it
    assert {rel for rel, _ in readers} == {rel for rel, _ in et.GOLD_READERS}
    assert len(et.GOLD_READERS) == 9


def test_shadow_refuses_a_target_missing_a_subtable(toy):
    bad = _table(toy["tmp"] / "bad11" / et.TABLE_11, N_11,
                 subtables=[s for s in et.SUBTABLES if s != "works_affil"])
    out = toy["tmp"] / "work" / "edge_table"
    with pytest.raises(ValueError, match="works_affil"):
        et.build_ssd_shadow(toy["real"], out, bad)
    assert not (out / "openalex_pipeline").exists()
    # a subtable that only the real 07-05 table holds is required too
    _parquet(toy["derived"] / et.TABLE_0705 / "refs_edges" / "bucket=000" / "part.parquet", 1)
    with pytest.raises(ValueError, match="refs_edges"):
        et.build_ssd_shadow(toy["real"], out, toy["target"])
    assert not (out / "openalex_pipeline").exists()


def test_shadow_does_not_require_a_0705_subtable_that_holds_no_data(toy):
    """t-big-03 (B4): the real 07-05 table holds canonical_id_map with 0 rows - its directory has only the U1
    provenance.json sidecar, no parquet file - and the 11-school table on S3 has no such directory, so the shadow
    (and the S10 reverse proof's cut) refused: 'lacks ['canonical_id_map']'. No reader can read a row from it under
    either name, so it is not required; the manifest lists it. The same directory with one parquet file is data and
    is required again (positive control)."""
    cim = toy["derived"] / et.TABLE_0705 / "canonical_id_map"
    cim.mkdir()
    (cim / "provenance.json").write_text('{"row_count": 0, "table": "canonical_id_map"}\n')
    out = toy["tmp"] / "work" / "edge_table"
    mf = et.build_ssd_shadow(toy["real"], out, toy["target"])
    assert "canonical_id_map" in mf["table_0705_subtables"]
    assert mf["table_0705_subtables_without_data"] == ["canonical_id_map"]
    assert "canonical_id_map" not in mf["target_subtables"]
    assert et._subtables_with_data(toy["derived"] / et.TABLE_0705) == sorted(et.SUBTABLES)
    _parquet(cim / "bucket=000" / "part.parquet", 1)
    with pytest.raises(ValueError, match="canonical_id_map"):
        et.build_ssd_shadow(toy["real"], toy["tmp"] / "work2" / "edge_table", toy["target"])
    assert not (toy["tmp"] / "work2" / "edge_table" / "openalex_pipeline").exists()
    # a SUBTABLES member stays required even when the 07-05 copy of it is empty: the readers read it by name
    bare = _table(toy["tmp"] / "bare11" / et.TABLE_11, N_11, subtables=[s for s in et.SUBTABLES if s != "works_affil"])
    for p in (toy["derived"] / et.TABLE_0705 / "works_affil").rglob("*.parquet"):
        p.unlink()
    with pytest.raises(ValueError, match="works_affil"):
        et.build_ssd_shadow(toy["real"], toy["tmp"] / "work3" / "edge_table", bare)


def test_paths_file_changes_only_ssd_root(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text("# a toy base\n"
                    'repo_root: "."\n'
                    'legacy_v2_output: "/data/legacy/v2_output"\n'
                    'ssd_root: "/data/openalex_pipeline"   # the data disk\n'
                    "frames: data/frames\n"
                    "extra_key: some/rel/path\n"
                    'cal: "data/cal2026-10"\n', encoding="utf-8")
    shadow = tmp_path / "w" / "openalex_pipeline"
    out = et.write_paths_file(base, shadow, tmp_path / "out" / "paths.yaml")
    assert out == tmp_path / "out" / "paths.yaml"
    old, new = yaml.safe_load(base.read_text()), yaml.safe_load(out.read_text())
    assert set(old) == set(new)
    assert [k for k in old if old[k] != new[k]] == ["ssd_root"]
    assert new["ssd_root"] == str(shadow)
    # the leaf the ported units assert, an absolute path, and exactly one ssd_root line are required
    with pytest.raises(ValueError):
        et.write_paths_file(base, tmp_path / "w" / "not_the_leaf", tmp_path / "x.yaml")
    with pytest.raises(ValueError):
        et.write_paths_file(base, pathlib.Path("rel/openalex_pipeline"), tmp_path / "x.yaml")
    nossd = tmp_path / "nossd.yaml"
    nossd.write_text("frames: data/frames\n", encoding="utf-8")
    with pytest.raises(ValueError):
        et.write_paths_file(nossd, shadow, tmp_path / "x.yaml")


def test_env_for_on_is_idempotent_and_the_cli_prints_the_paths_file(toy, capsys, monkeypatch):
    kw = dict(real_ssd_root=toy["real"], work_dir=toy["tmp"] / "work", base_paths=toy["base"])
    with pytest.raises(ValueError):
        et.env_for("u1_some_other_table", **kw)
    first = et.env_for(et.TABLE_11, **kw)
    assert et.env_for(et.TABLE_11, **kw) == first            # a second stage reuses the same shadow
    # the CLI builds the same thing under --out and prints the paths file
    out = toy["tmp"] / "cli_out"
    rc = et.main(["shadow", "--target", str(toy["target"]), "--out", str(out), "--base-paths", str(toy["base"])])
    assert rc == 0
    printed = capsys.readouterr().out.strip().splitlines()[-1]
    assert printed == str(out / et.PATHS_NAME)
    assert yaml.safe_load(pathlib.Path(printed).read_text())["ssd_root"] == str(out / "openalex_pipeline")
    assert json.loads((out / et.MANIFEST_NAME).read_text())["target_realpath"] == _real(toy["target"])
    # a base paths file whose ssd_root is not the real root the shadow mirrors is refused
    other = toy["tmp"] / "other.yaml"
    other.write_text(toy["base"].read_text().replace(str(toy["real"]), "/elsewhere/openalex_pipeline"))
    with pytest.raises(ValueError):
        et.env_for(et.TABLE_11, real_ssd_root=toy["real"], work_dir=toy["tmp"] / "work2", base_paths=other)
    # $SAR_SSD_ROOT beats any paths file in pipeline.lib.paths, so the on path refuses to run under it
    monkeypatch.setenv("SAR_SSD_ROOT", str(toy["real"]))
    with pytest.raises(RuntimeError):
        et.env_for(et.TABLE_11, **kw)
    assert et.env_for(et.TABLE_0705, **kw) == {}
    # the CLI runs only on an R1 instance
    monkeypatch.delenv("SAR_SSD_ROOT")
    monkeypatch.setenv("SAR_HOST", "my-mac")
    with pytest.raises(SystemExit):
        et.main(["shadow", "--target", str(toy["target"]), "--out", str(out), "--base-paths", str(toy["base"])])
