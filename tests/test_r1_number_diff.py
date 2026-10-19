# -*- coding: utf-8 -*-
"""tools/r1_number_diff.py (R1 F24') - the new-vs-October number table, on toy ledgers.

Small runner only: every ledger here is a toy JSON written to tmp_path. No data, no estimate.
"""
from __future__ import annotations

import ast
import csv
import fnmatch
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import r1_number_diff as nd   # noqa: E402

OCT = "2026-10-23"
HEADER = ["ledger", "key", "old", "new", "status", "same_at_3dp", "sign_change", "p_crosses_005", "printed"]
#: the ten installed names, written out by hand (independent of the tool's own constant)
TEN = ["data_numbers_2026-10-23.json", "data_numbers_2026-10-23_p1p2.json", "data_numbers_2026-10-23_p3afar.json",
       "data_numbers_2026-10-23_robustness.json", "data_numbers_2026-10-23_funnel.json",
       "data_numbers_2026-10-23_gaps_zenou.json", "data_numbers_2026-10-23_gaps_zero_dose.json",
       "data_numbers_2026-10-23_gaps_switchers.json", "data_numbers_2026-10-23_gaps_switchers_p1p2.json",
       "data_numbers_2026-10-23_gaps_toy.json"]
SUFFIX_OF = {"": "main", "_p1p2": "p1p2", "_p3afar": "p3afar", "_robustness": "robustness", "_funnel": "funnel",
             "_gaps_zenou": "gaps_zenou", "_gaps_zero_dose": "gaps_zero_dose", "_gaps_switchers": "gaps_switchers",
             "_gaps_switchers_p1p2": "gaps_switchers_p1p2", "_gaps_toy": "gaps_toy"}


def _tree(d: pathlib.Path, date: str, ledgers: dict | None = None, skip=()) -> pathlib.Path:
    """Write all ten ledgers of one side; a suffix not in `ledgers` gets {"n": 1}."""
    d.mkdir(parents=True, exist_ok=True)
    ledgers = ledgers or {}
    for suf in SUFFIX_OF:
        if suf in skip:
            continue
        (d / f"data_numbers_{date}{suf}.json").write_text(json.dumps(ledgers.get(suf, {"n": 1}), indent=1),
                                                          encoding="utf-8")
    return d


def _run(tmp_path, old, new, *, old_date=OCT, new_date=OCT, printed=None, out="out"):
    argv = ["--old", str(old), "--old-date", old_date, "--new", str(new), "--new-date", new_date,
            "--out", str(tmp_path / out)]
    if printed is not None:
        argv += ["--printed", str(printed)]
    return nd.main(argv)


def _rows(tmp_path, out="out"):
    with open(tmp_path / out / "ledger_diff.csv", newline="", encoding="utf-8") as f:
        r = list(csv.reader(f))
    return r[0], r[1:]


def _md(tmp_path, out="out"):
    return (tmp_path / out / "number_table.md").read_text(encoding="utf-8")


OLD_MAIN = {"_source": "October note", "a": 1.5, "b": 2.0, "gone": 3, "lst": [1, 2], "nest": {"x": "s"},
            "_provenance": {"gen": "ledger_main.py"}}
NEW_MAIN = {"_source": "M note", "a": 1.5, "b": 2.5, "lst": [1, 3], "nest": {"x": "s"}, "new_k": 7,
            "_provenance": {"gen": "ledger_main.py", "canon": "M"}}


def test_statuses_on_toy_ledgers(tmp_path):
    old = _tree(tmp_path / "old", OCT, {"": OLD_MAIN})
    new = _tree(tmp_path / "new", OCT, {"": NEW_MAIN})
    assert _run(tmp_path, old, new) == 0
    header, rows = _rows(tmp_path)
    assert header == HEADER
    main = [r for r in rows if r[0] == "main"]
    assert main == [
        ["main", "a", "1.5", "1.5", "unchanged", "true", "false", "", ""],
        ["main", "b", "2.0", "2.5", "changed", "false", "false", "", ""],
        ["main", "gone", "3", "", "dropped", "", "", "", ""],
        ["main", "lst[0]", "1", "1", "unchanged", "true", "false", "", ""],
        ["main", "lst[1]", "2", "3", "changed", "false", "false", "", ""],
        ["main", "nest.x", '"s"', '"s"', "unchanged", "", "", "", ""],
        ["main", "new_k", "", "7", "added", "", "", "", ""],
    ]
    # every other ledger: its one leaf, unchanged; ledgers in the fixed order
    others = [r for r in rows if r[0] != "main"]
    assert [r[0] for r in others] == [SUFFIX_OF[s] for s in SUFFIX_OF if s]
    assert all(r[1:5] == ["n", "1", "1", "unchanged"] for r in others)
    md = _md(tmp_path)
    assert "| main | 7 | 3 | 2 | 1 | 1 |" in md

    # switch-off proof: October against a copy of itself -> every row unchanged
    copy = _tree(tmp_path / "copy", OCT, {"": OLD_MAIN})
    assert _run(tmp_path, old, copy, out="self") == 0
    _, rows = _rows(tmp_path, "self")
    assert rows and {r[4] for r in rows} == {"unchanged"}
    assert "No changed, added or dropped leaves." in _md(tmp_path, "self")


def test_cut_cells_show_as_dropped_cut_by_plan(tmp_path):
    rob_old = {"dosebin3": {"econ": {"p1": {"ate_log": -0.07}, "p3_full": {"ate_pp": 0.023}}}, "top5": {"x": 1}}
    rob_new = {"top5": {"x": 1}}
    old = _tree(tmp_path / "old", OCT, {"_robustness": rob_old})
    new = _tree(tmp_path / "new", OCT, {"_robustness": rob_new})
    assert _run(tmp_path, old, new) == 0
    _, rows = _rows(tmp_path)
    cut = [r for r in rows if r[0] == "robustness" and r[1].startswith("dosebin3.")]
    assert [r[4] for r in cut] == ["dropped", "dropped"]
    md = _md(tmp_path)
    for line in md.splitlines():
        if "dosebin3.econ" in line:
            assert "cut by plan (F19)" in line
    assert md.count("cut by plan (F19)") >= 2


def test_underscore_keys_and_provenance_ignored(tmp_path):
    o = {"_provenance": {"k": 1}, "_october": {"v": 1}, "_diff_vs_october": {"x": 2},
         "v": {"_inputs": {"z": 1}, "w": 1}}
    n = {"_provenance": {"k": 9}, "_october": {"v": 8}, "_diff_vs_october": {"x": 7},
         "v": {"_inputs": {"z": 6}, "w": 1}}
    old = _tree(tmp_path / "old", OCT, {"": o})
    new = _tree(tmp_path / "new", OCT, {"": n})
    assert _run(tmp_path, old, new) == 0
    _, rows = _rows(tmp_path)
    keys = [r[1] for r in rows]
    for bad in ("_provenance", "_october", "_diff_vs_october", "_inputs"):
        assert not any(bad in k for k in keys)
        assert bad not in _md(tmp_path)
    assert {r[4] for r in rows} == {"unchanged"}
    assert ["main", "v.w"] in [r[:2] for r in rows]


def test_sign_change_and_p_crossing_flags(tmp_path):
    o = {"zz_flat": 5, "q": 0.23550, "est": -0.04, "p_joint_effects": 0.04, "placebo_p": 0.01, "p1": 0.04}
    n = {"zz_flat": 6, "q": 0.23549, "est": 0.02, "p_joint_effects": 0.06, "placebo_p": 0.02, "p1": 0.06}
    old = _tree(tmp_path / "old", OCT, {"": o})
    new = _tree(tmp_path / "new", OCT, {"": n})
    assert _run(tmp_path, old, new) == 0
    _, rows = _rows(tmp_path)
    by = {r[1]: r for r in rows if r[0] == "main"}
    assert by["q"][4:8] == ["changed", "true", "false", ""]
    assert by["est"][4:8] == ["changed", "false", "true", ""]
    assert by["p_joint_effects"][4:8] == ["changed", "false", "false", "true"]
    assert by["placebo_p"][4:8] == ["changed", "false", "false", "false"]
    assert by["p1"][7] == ""                                # p1 is Panel 1, not a p-value
    md = _md(tmp_path)
    # sign changes and p crossings first, in the flag section and inside the ledger group
    assert "## Sign changes and p crossings" in md
    head, _, body = md.partition("## Changed, added and dropped")
    assert "| est |" in head and "| p_joint_effects |" in head and "| q |" not in head
    # inside the main group: the two flagged rows, then the plain changes in ledger order (zz_flat, q, ...)
    assert body.index("| est |") < body.index("| zz_flat |") < body.index("| q |")
    assert body.index("| p_joint_effects |") < body.index("| zz_flat |")


def test_pairing_by_suffix_and_dates(tmp_path, capsys):
    old = _tree(tmp_path / "old", OCT)
    # stray dated files on the old side: never read (their keys would trip the C10 refusal if they were)
    (old / "data_numbers_2026-08-16.json").write_text(json.dumps({"old79": {"x": 1}}), encoding="utf-8")
    (old / "data_numbers_2026-08-22_p3afar.json").write_text(json.dumps({"new37": 1}), encoding="utf-8")
    new = _tree(tmp_path / "new", "2026-11-02", skip=("_funnel",))
    # an October-dated file in the new dir is not the new side
    (new / f"data_numbers_{OCT}.json").write_text(json.dumps({"n": 999}), encoding="utf-8")
    rc = _run(tmp_path, old, new, new_date="2026-11-02")
    assert rc == 2                                        # funnel unpaired
    _, rows = _rows(tmp_path)
    assert [r for r in rows if r[0] == "main"] == [["main", "n", "1", "1", "unchanged", "true", "false", "", ""]]
    assert [r[4] for r in rows if r[0] == "funnel"] == ["dropped"]
    err = capsys.readouterr().err
    assert "WARN" in err and "funnel" in err
    assert "WARN" in _md(tmp_path)

    # an unexpected file carrying the selected date -> exit 2, not read
    new2 = _tree(tmp_path / "new2", "2026-11-02")
    (new2 / "data_numbers_2026-11-02_extra.json").write_text(json.dumps({"n": 5}), encoding="utf-8")
    assert _run(tmp_path, old, new2, new_date="2026-11-02", out="out2") == 2
    assert "data_numbers_2026-11-02_extra.json" in capsys.readouterr().err
    _, rows = _rows(tmp_path, "out2")
    assert all(r[0] != "extra" for r in rows) and {r[4] for r in rows} == {"unchanged"}

    # the same two complete trees, both selected by their own dates -> exit 0
    new3 = _tree(tmp_path / "new3", "2026-11-02")
    assert _run(tmp_path, old, new3, new_date="2026-11-02", out="out3") == 0


def test_an_empty_or_absent_ledger_has_no_leaves(tmp_path):
    """t-0023: flatten({}) gave a root leaf '' = {}, so a missing ledger listed a phantom 'added' row."""
    assert nd.flatten({}) == {} and nd.flatten([]) == {}
    assert nd.flatten({"a": {}, "b": [], "_p": {"x": 1}}) == {"a": {}, "b": []}   # keyed empty containers stay leaves
    old = _tree(tmp_path / "old", OCT)
    new = _tree(tmp_path / "new", OCT, {"_funnel": {}})                   # the file is there, but holds {}
    assert _run(tmp_path, old, new) == 0
    _, rows = _rows(tmp_path)
    assert [r[1:5] for r in rows if r[0] == "funnel"] == [["n", "1", "", "dropped"]]
    assert all(r[1] for r in rows)                                          # no root leaf '' on either side


def test_no_attribution_or_split_rows(tmp_path):
    assert nd.HEADER == HEADER
    with pytest.raises(SystemExit) as e:
        nd.main(["--old", "a", "--new", "b", "--new-date", OCT, "--out", "c", "--config", "M.json"])
    assert e.value.code == 2
    old = _tree(tmp_path / "old", OCT)
    for i, bad in enumerate(({"p1_old79": {"ate": 1}}, {"x": {"split": {"new37": 2}}}, {"y": [{"old79_n": 1}]})):
        new = _tree(tmp_path / f"new{i}", OCT, {"_p1p2": bad})
        assert _run(tmp_path, old, new, out=f"o{i}") == 2
        assert not (tmp_path / f"o{i}" / "ledger_diff.csv").exists()
        assert not (tmp_path / f"o{i}" / "number_table.md").exists()


def test_printed_column_only_from_the_list(tmp_path):
    old = _tree(tmp_path / "old", OCT, {"": OLD_MAIN})
    new = _tree(tmp_path / "new", OCT, {"": NEW_MAIN})
    assert _run(tmp_path, old, new) == 0
    _, rows = _rows(tmp_path)
    assert {r[8] for r in rows} == {""}                  # never guessed
    pl = tmp_path / "printed.txt"
    pl.write_text("# sentinel keys\nmain\tb\nlst\n\n", encoding="utf-8")
    assert _run(tmp_path, old, new, printed=pl, out="p") == 0
    _, rows = _rows(tmp_path, "p")
    by = {(r[0], r[1]): r[8] for r in rows}
    assert by[("main", "b")] == "true" and by[("main", "lst[0]")] == "true" and by[("main", "lst[1]")] == "true"
    assert by[("main", "a")] == "false" and by[("p1p2", "n")] == "false"
    pj = tmp_path / "printed.json"
    pj.write_text(json.dumps({"main": ["nest"]}), encoding="utf-8")
    assert _run(tmp_path, old, new, printed=pj, out="pj") == 0
    _, rows = _rows(tmp_path, "pj")
    by = {(r[0], r[1]): r[8] for r in rows}
    assert by[("main", "nest.x")] == "true" and by[("main", "b")] == "false"


def test_old_side_layout_matches_the_f1_upload(tmp_path):
    up = json.loads((REPO / "data/cal2026-10r1/aws/uploads/v3up_2026-10-13.json").read_text(encoding="utf-8"))
    (bt,) = [e for e in up if e["key"] == "base_tree"]
    assert bt["prefix"] == "r1/ref/october/ledgers_base_tree/"
    names = [nd.file_name(OCT, s) for s in nd.SUFFIXES]
    assert sorted(names) == sorted(TEN) and len(names) == bt["files"] == 10
    assert all(fnmatch.fnmatch(n, bt["include"]) for n in names)
    # the same file transform as tools/repin_thesis_2026-10/install.py (read as text, not imported)
    tree = ast.parse((REPO / "tools/repin_thesis_2026-10/install.py").read_text(encoding="utf-8"))
    const = {t.id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
             for t in n.targets if isinstance(t, ast.Name) and t.id in ("DATE", "COPIED", "GAPS")}
    inst = {f"data_numbers_{const['DATE']}.json"} | {f"data_numbers_{const['DATE']}_{x}.json" for x in const["COPIED"]} \
        | {f"data_numbers_{const['DATE']}_gaps_{x}.json" for x in const["GAPS"]}
    assert inst == set(names)
    # the ten names, laid out as the upload, all pair (October against itself)
    d = tmp_path / "ledgers_base_tree"
    d.mkdir()
    for n in TEN:
        (d / n).write_text(json.dumps({"k": 0.5}), encoding="utf-8")
    assert _run(tmp_path, d, d) == 0
    _, rows = _rows(tmp_path)
    assert len(rows) == 10 and {r[4] for r in rows} == {"unchanged"}
