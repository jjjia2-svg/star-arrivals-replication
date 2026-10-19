#!/usr/bin/env python3
"""R1 N2 (J1a path): chemistry / maths M reads the 11-school edge table under the 07-05 name.

  edge_table.py shadow --target DIR --out DIR --base-paths FILE     (prints the shadow paths file)

Why a shadow and not an edit. The October chem/maths chain reads `u1_edges_full_2026-07-05` in four
places, all through `<ssd_root>/derived` (GOLD_READERS): the prodlib config globs (edges, works,
work_first_pub; configs/{chemistry,math_stats}.json:13-15), 10_build_union_frame_gold.py:66 (edges,
works, works_affil), 20_rebuild_y_gold.py:52 (edges, works; its fwci_baseline_pop only feeds the
unused machineold variant) and 30_build_panels23_gold.py:60 (edges). Design v3 puts chem/maths
ranking, colleague output, ties and dose on the 11-school table. Rather than edit or clone pinned
code, this builds a shadow data root under $WORK:

  <out>/openalex_pipeline/derived/<every real derived entry>  -> symlink to the real entry
  <out>/openalex_pipeline/derived/u1_edges_full_2026-07-05     -> symlink to the 11-school table
  <out>/openalex_pipeline/<every other top-level entry>        -> symlink (snapshot/ included)

plus a copy of the base paths file (config/r1/paths_aws.yaml) whose only change is `ssd_root`. A
process started with SAR_PATHS_CONFIG = that copy runs the pinned builders byte for byte; only the
data behind the name changes. edge_table_manifest.json records the swap (house precedent:
frames_stage.Shadow / stage.build_shadow stage new inputs under frozen names).

The target must hold every SUBTABLES member and every subtable the real 07-05 table holds WITH DATA (at
least one parquet file). A 07-05 subtable without a parquet file - canonical_id_map: 0 rows, only U1's
provenance.json - gives no reader a row under either name and is absent from the 11-school table on S3
(an empty directory is never uploaded), so it is listed in the manifest
(table_0705_subtables_without_data) and not required (t-big-03, the S10 reverse proof's setup failure).

Switch (pipeline/lib/r1_config.py `chemmath_edges`): off = TABLE_0705 -> env_for returns {} and
writes nothing, so the stage keeps the B0 paths file; on = TABLE_11 -> {'SAR_PATHS_CONFIG': <copy>}.

Rules for callers
  * pipeline.lib.paths caches its config (lru_cache) on first use: SAR_PATHS_CONFIG must be in the
    environment when the process STARTS (stage commands export it; run_frames subprocesses inherit).
  * $SAR_SSD_ROOT beats any paths file in pipeline.lib.paths, so the on path refuses to run under it.
  * Only chem/maths M stage processes (and J1a new_numbers) may carry this env. Any code in such a
    process that reads the 07-05 name gets the 11-school table; econ stages and the paper layer
    (analysis/paper/ledger_funnel.py reads 07-05) must not carry it.
  * The shadow is a snapshot of the real derived/ listing at build time: build it after the data
    sync / relink, and a rerun over a shadow whose recorded links no longer match the disk stops.
  * New entries a process writes directly into <shadow>/derived land in the shadow, not the real root
    (the chem/maths builders write under their run dirs, not under derived_root).
Relative values in the paths file resolve against the repo root (analysis.lib.paths.load_paths),
so the copy may live anywhere.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

import yaml

TABLE_0705 = "u1_edges_full_2026-07-05"
TABLE_11 = "u1_full_11school_2026-07-16"
TABLES = (TABLE_0705, TABLE_11)
#: the subtables the chem/maths readers take from the table (prodlib globs + the three gold builders)
SUBTABLES = ("authorship_edges", "works", "works_affil", "work_first_pub", "fwci_baseline_pop")
#: == pipeline.lib.paths.SSD_ROOT_LEAF (not imported: that module fixes its config file at import)
SSD_ROOT_LEAF = "openalex_pipeline"
MANIFEST_NAME = "edge_table_manifest.json"
PATHS_NAME = "paths_edge_table.yaml"
WORK_SUBDIR = "edge_table"
SCHEMA = "sar.r1.edge_table_shadow.v1"
HOSTS = ("ec2-r1-test", "ec2-r1")

_CFG = "pipeline/frames/cal2026-10/configs"
_GOLD = "pipeline/frames/multidisc_gold_2026-08-10/code"
#: (repo path, line) of every read of TABLE_0705 in the chem/maths chain; each goes through
#: derived_root (`_sar_derived_root() / "..."` or `${DERIVED}/...`), so the shadow covers them all.
GOLD_READERS = frozenset(
    {(f"{_CFG}/{f}.json", n) for f in ("chemistry", "math_stats") for n in (13, 14, 15)}
    | {(f"{_GOLD}/10_build_union_frame_gold.py", 77), (f"{_GOLD}/20_rebuild_y_gold.py", 54),
       (f"{_GOLD}/30_build_panels23_gold.py", 63)})
#: files the reader scan (tests/test_r1_edge_table.py) reads: the readers plus the chem/maths drivers,
#: which must name no edge table themselves.
READER_SCAN = (f"{_CFG}/chemistry.json", f"{_CFG}/math_stats.json",
               f"{_GOLD}/10_build_union_frame_gold.py", f"{_GOLD}/20_rebuild_y_gold.py",
               f"{_GOLD}/30_build_panels23_gold.py",
               "pipeline/frames/cal2026-10/stage.py", "pipeline/frames/cal2026-10/run_cal_frames_chemmath.py")

_SSD_LINE = re.compile(r"(?m)^ssd_root:[^\n]*$")


def _abs(p) -> pathlib.Path:
    return pathlib.Path(os.path.abspath(os.path.expanduser(str(p))))


def _inside(path: pathlib.Path, root: pathlib.Path) -> bool:
    a, b = os.path.realpath(path), os.path.realpath(root)
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


def _subtables(table: pathlib.Path) -> list[str]:
    return sorted(e.name for e in os.scandir(table) if e.is_dir() and not e.name.startswith(("_", ".")))


def _has_data(sub: pathlib.Path) -> bool:
    """A subtable holds data when at least one parquet file lies under it. U1 writes a 0-row table as its
    directory plus the provenance.json sidecar only (the real 07-05 canonical_id_map: row_count 0), and
    `aws s3 sync` uploads no empty directory, so such a table may exist under one name and not the other."""
    for _dir, _subdirs, files in os.walk(sub):
        if any(f.endswith(".parquet") for f in files):
            return True
    return False


def _subtables_with_data(table: pathlib.Path) -> list[str]:
    return [s for s in _subtables(table) if _has_data(table / s)]


def _plan(real_ssd_root, out_dir, target) -> dict:
    """The manifest of the shadow build_ssd_shadow would make. Validates; writes nothing."""
    real, out, tgt = _abs(real_ssd_root), _abs(out_dir), _abs(target)
    derived = real / "derived"
    if not derived.is_dir():
        raise FileNotFoundError(f"no derived/ under the real data root: {derived}")
    old = derived / TABLE_0705
    if not old.is_dir():
        raise FileNotFoundError(f"the real data root has no {TABLE_0705}: {old}")
    if not tgt.is_dir():
        raise FileNotFoundError(f"target table is not a directory: {tgt}")
    if _inside(out, real) or _inside(real, out):
        raise ValueError(f"the shadow ({out}) and the real data root ({real}) must not nest")
    have = _subtables(tgt)
    old_subs = _subtables(old)
    # a 07-05 subtable without a parquet file (canonical_id_map: 0 rows) gives no reader a row under either
    # name, so the target need not hold it (t-big-03); a SUBTABLES member is read by name and stays required
    without_data = sorted(set(old_subs) - set(_subtables_with_data(old)))
    missing = sorted(((set(old_subs) - set(without_data)) | set(SUBTABLES)) - set(have))
    if missing:
        raise ValueError(f"target {tgt} lacks subtable(s) {missing} that {TABLE_0705} holds with data or the "
                         f"chem/maths readers read; refusing to stage it under the 07-05 name")
    entries = [{"name": n, "link": str(real / n), "realpath": os.path.realpath(real / n)}
               for n in sorted(os.listdir(real)) if n != "derived"]
    for n in sorted(os.listdir(derived)):
        link = tgt if n == TABLE_0705 else derived / n
        entries.append({"name": f"derived/{n}", "link": str(link), "realpath": os.path.realpath(link)})
    return {"schema": SCHEMA, "swapped_name": TABLE_0705, "target": str(tgt),
            "target_realpath": os.path.realpath(tgt), "real_ssd_root": str(real),
            "shadow_ssd_root": str(out / SSD_ROOT_LEAF), "entries": entries,
            "target_subtables": have, "table_0705_subtables": old_subs,
            "table_0705_subtables_without_data": without_data}


def _verify(mf: dict) -> None:
    """The shadow on disk holds exactly the manifest's entries, each resolving where it says."""
    shadow = pathlib.Path(mf["shadow_ssd_root"])
    want = sorted(e["name"] for e in mf["entries"])
    have = sorted([n for n in os.listdir(shadow) if n != "derived"]
                  + [f"derived/{n}" for n in os.listdir(shadow / "derived")])
    if have != want:
        raise RuntimeError(f"shadow {shadow} entries differ from its manifest: "
                           f"extra {sorted(set(have) - set(want))}, missing {sorted(set(want) - set(have))}")
    for e in mf["entries"]:
        got = os.path.realpath(shadow / e["name"])
        if got != e["realpath"]:
            raise RuntimeError(f"shadow entry {e['name']} resolves to {got}, not {e['realpath']}")


def build_ssd_shadow(real_ssd_root: pathlib.Path, out_dir: pathlib.Path, target: pathlib.Path) -> dict:
    """Build <out_dir>/openalex_pipeline (one symlink per real entry, the 07-05 name -> target) and
    <out_dir>/edge_table_manifest.json. Refuses an existing shadow; returns the manifest."""
    mf = _plan(real_ssd_root, out_dir, target)
    shadow = pathlib.Path(mf["shadow_ssd_root"])
    if os.path.lexists(shadow):
        raise FileExistsError(f"shadow data root already exists: {shadow}")
    (shadow / "derived").mkdir(parents=True)
    for e in mf["entries"]:
        os.symlink(e["link"], shadow / e["name"])
    _verify(mf)
    (shadow.parent / MANIFEST_NAME).write_text(json.dumps(mf, indent=1, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
    return mf


def write_paths_file(base_yaml: pathlib.Path, shadow_ssd_root: pathlib.Path, out: pathlib.Path) -> pathlib.Path:
    """Copy base_yaml to out with only the `ssd_root` line changed; assert every other key is equal."""
    shadow = pathlib.Path(shadow_ssd_root)
    if not shadow.is_absolute() or shadow.name != SSD_ROOT_LEAF:
        raise ValueError(f"shadow ssd_root must be absolute and end in '{SSD_ROOT_LEAF}': {shadow}")
    base = pathlib.Path(base_yaml)
    text = base.read_text(encoding="utf-8")
    if len(_SSD_LINE.findall(text)) != 1:
        raise ValueError(f"{base} must hold exactly one top-level 'ssd_root:' line")
    new = (f"# R1 N2 (pipeline/aws/r1/edge_table.py): copy of {base} with only ssd_root changed\n"
           + _SSD_LINE.sub(lambda _m: "ssd_root: " + json.dumps(str(shadow)), text))
    out = pathlib.Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(new, encoding="utf-8")
    old_d, new_d = yaml.safe_load(text), yaml.safe_load(out.read_text(encoding="utf-8"))
    if set(old_d) != set(new_d) or any(old_d[k] != new_d[k] for k in old_d if k != "ssd_root") \
            or new_d["ssd_root"] != str(shadow):
        raise AssertionError(f"{out} differs from {base} in more than ssd_root")
    return out


def _base_ssd_root(base_paths) -> pathlib.Path:
    d = yaml.safe_load(pathlib.Path(base_paths).read_text(encoding="utf-8")) or {}
    v = str(d.get("ssd_root", "")).strip()
    if not v or not pathlib.Path(os.path.expanduser(v)).is_absolute():
        raise ValueError(f"{base_paths} has no absolute ssd_root")
    return _abs(v)


def ensure_shadow(real_ssd_root, out_dir, target, base_paths) -> tuple[dict, pathlib.Path]:
    """Build the shadow and its paths file, or reuse an identical one (a second stage of the same job)."""
    if _base_ssd_root(base_paths) != _abs(real_ssd_root):
        raise ValueError(f"the base paths file's ssd_root ({_base_ssd_root(base_paths)}) is not the real "
                         f"root the shadow mirrors ({_abs(real_ssd_root)})")
    out = _abs(out_dir)
    mf_path = out / MANIFEST_NAME
    if mf_path.is_file():
        mf = json.loads(mf_path.read_text(encoding="utf-8"))
        if mf != _plan(real_ssd_root, out, target):
            raise RuntimeError(f"stale shadow at {out}: its manifest no longer matches the data root; "
                               f"build a fresh one in a new directory")
        _verify(mf)
    else:
        mf = build_ssd_shadow(real_ssd_root, out, target)
    return mf, write_paths_file(pathlib.Path(base_paths), pathlib.Path(mf["shadow_ssd_root"]), out / PATHS_NAME)


def _refuse_ssd_override() -> None:
    if os.environ.get("SAR_SSD_ROOT", "").strip():
        raise RuntimeError("$SAR_SSD_ROOT is set: it overrides ssd_root in any paths file "
                           "(pipeline.lib.paths.ENV_OVERRIDES), so the shadow would be ignored. Unset it.")


def env_for(table_name: str, *, real_ssd_root, work_dir, base_paths) -> dict[str, str]:
    """The env a chem/maths M process needs for `table_name` (the chemmath_edges switch value)."""
    if table_name not in TABLES:
        raise ValueError(f"table_name must be one of {TABLES}, got {table_name!r}")
    if table_name == TABLE_0705:
        return {}
    _refuse_ssd_override()
    target = _abs(real_ssd_root) / "derived" / table_name
    _, paths_file = ensure_shadow(real_ssd_root, _abs(work_dir) / WORK_SUBDIR, target, base_paths)
    return {"SAR_PATHS_CONFIG": str(paths_file)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sh = sub.add_parser("shadow", help="build (or reuse) the shadow data root and print its paths file")
    for k in ("--target", "--out", "--base-paths"):
        sh.add_argument(k, required=True)
    a = ap.parse_args(argv)
    if os.environ.get("SAR_HOST", "").strip() not in HOSTS:
        raise SystemExit("R1 rule: edge_table.py runs only on an R1 instance ($SAR_HOST)")
    _refuse_ssd_override()
    _, paths_file = ensure_shadow(_base_ssd_root(a.base_paths), a.out, a.target, a.base_paths)
    print(paths_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
