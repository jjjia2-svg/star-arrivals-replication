# R1 N10 (unit W1-PTABLES): the base tree's hand-edited tables as a generator variant.
#
# The base manuscript tree of 2026-10-11 (restricted archive, not shipped; spec 2026-10-12 "Base
# tree for the paper") carries hand edits in four generated tables: tab_main_results,
# tab_panels_overview, tab_robustness (draft_2026_09_13_tables.py) and tab_rob_p1
# (tables_robustness.py: the "Dose in three bins" row replaced by a 2026-10-04 comment).
# `--tree base_2026_10_11` must reproduce those bytes on the October ledgers; the default
# `--tree thesis_report` must keep today's bytes (tools/check_paper.py section B compares them with the
# legacy thesis_report/tables). Byte targets and pins: tests/fixtures/r1_paper/base_tree_2026-10-11/ (not shipped).
#
# The first four tests need only the repo (fixture ledgers in git, analysis/expected for the age-gap
# cap). The last one runs the real ledger chain and is deselected by default (big host only).
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import config_file, load_paths  # noqa: E402
from analysis.lib import canon  # noqa: E402

P = load_paths()
FIX = REPO / "tests/fixtures/r1_paper/base_tree_2026-10-11"
if not FIX.is_dir():   # public copy: the manuscript fixtures are not shipped
    pytest.skip("needs the manuscript fixtures in tests/fixtures/r1_paper/ (not shipped)", allow_module_level=True)
FIX_TABLES = FIX / "tables"
FIX_LEDGERS = FIX / "ledgers"
DRAFT = REPO / "analysis/paper/draft_2026_09_13_tables.py"
ROB = REPO / "analysis/paper/tables_robustness.py"
BASE = "base_2026_10_11"
DRAFT_NAMES = ("tab_main_results.tex", "tab_robustness.tex", "tab_panels_overview.tex")
ROB_APPENDIX = ("tab_rob_p1.tex", "tab_rob_p2.tex", "tab_rob_p3.tex")
DATE = "2026-10-23"
# undated output/paper ledger name -> dated thesis ledger name (byte copies, install.py COPIED)
UNDATED = {"p1p2": f"data_numbers_{DATE}_p1p2.json", "p3afar": f"data_numbers_{DATE}_p3afar.json",
           "robustness": f"data_numbers_{DATE}_robustness.json"}
FLAG = "% cal2026-10 FLAG for the author"


def _legacy_sha():
    """The switch-off pins: sha256 of today's legacy thesis_report/tables, as SOURCE.md records them."""
    out = {}
    for line in (FIX / "SOURCE.md").read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"legacy-sha256 ([0-9a-f]{64})  (tab_\w+\.tex)", line.strip())
        if m:
            out[m.group(2)] = m.group(1)
    assert len(out) == 13, sorted(out)
    return out


def _draft(out, *args):
    r = subprocess.run([sys.executable, str(DRAFT), "--out-dir", str(out), *args],
                       capture_output=True, text=True, cwd=REPO)
    return r


def _paths_override(tmp, output_root):
    """A paths.yaml equal to the one in force except `output` (relative keys still resolve against the
    repo root: analysis.lib.paths.load_paths)."""
    raw = yaml.safe_load(config_file().read_text())
    raw["output"] = str(output_root)
    cfg = tmp / "paths_override.yaml"
    cfg.write_text(yaml.safe_dump(raw, allow_unicode=True))
    return cfg


def _rob(cfg, *args):
    env = dict(os.environ, SAR_PATHS_CONFIG=str(cfg))
    return subprocess.run([sys.executable, str(ROB), *args], capture_output=True, text=True, cwd=REPO, env=env)


def _undated_ledgers(paper_dir, src_dir):
    paper_dir.mkdir(parents=True, exist_ok=True)
    for short, dated in UNDATED.items():
        shutil.copyfile(src_dir / dated, paper_dir / f"data_numbers_{short}.json")


# ---------------------------------------------------------------------------
def test_draft_tables_base_variant_byte_equal(tmp_path):
    r = _draft(tmp_path, "--tree", BASE, "--ledger-dir", str(FIX_LEDGERS))
    assert r.returncode == 0, r.stdout + r.stderr
    for name in DRAFT_NAMES:
        assert (tmp_path / name).read_bytes() == (FIX_TABLES / name).read_bytes(), name
    checks = json.loads((tmp_path / "NOTE_CHECKS.json").read_text())
    assert checks and all(c["holds"] for c in checks), [c for c in checks if not c["holds"]]


@pytest.mark.parametrize("ledger_dir", ["fixture", "default"])
def test_draft_tables_default_unchanged(tmp_path, ledger_dir):
    args = ["--ledger-dir", str(FIX_LEDGERS)] if ledger_dir == "fixture" else []
    if ledger_dir == "default" and not (P["legacy_thesis"] / "thesis_report").is_dir():
        pytest.skip("legacy thesis_report not on this machine (the fixture case covers the bytes)")
    pins = _legacy_sha()
    r = _draft(tmp_path, *args)                       # no --tree: the default is thesis_report
    assert r.returncode == 0, r.stdout + r.stderr
    for name in DRAFT_NAMES:
        assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == pins[name], name
    r2 = _draft(tmp_path / "explicit", "--tree", "thesis_report", *args)
    assert r2.returncode == 0, r2.stdout + r2.stderr
    for name in DRAFT_NAMES:
        assert (tmp_path / "explicit" / name).read_bytes() == (tmp_path / name).read_bytes(), name


def test_tab_rob_p1_base_variant_drops_dose_three_bins(tmp_path):
    out_root = tmp_path / "out"
    paper = out_root / "paper"
    _undated_ledgers(paper, FIX_LEDGERS)
    rb = json.loads((paper / "data_numbers_robustness.json").read_text())
    assert "dosebin3" in rb["d7"]
    del rb["d7"]["dosebin3"]                            # M: F19 cuts these cells
    (paper / "data_numbers_robustness.json").write_text(json.dumps(rb, indent=1))
    cfg = _paths_override(tmp_path, out_root)

    r = _rob(cfg, "--tree", BASE)
    assert r.returncode == 0, r.stdout + r.stderr
    for name in ROB_APPENDIX:
        assert (paper / name).read_bytes() == (FIX_TABLES / name).read_bytes(), name
    text = (paper / "tab_rob_p1.tex").read_text()
    assert "Dose in three bins of equal size" not in text
    assert text.count('% 2026-10-04 author: row "Dose in three bins" deleted') == 1

    # the default variant still prints the row, so it still needs the cells (thesis_report is not
    # generated in M)
    r0 = _rob(cfg)
    assert r0.returncode != 0 and "dosebin3" in (r0.stdout + r0.stderr)


def test_tab_rob_default_variant_unchanged(tmp_path):
    out_root = tmp_path / "out"
    paper = out_root / "paper"
    _undated_ledgers(paper, FIX_LEDGERS)
    cfg = _paths_override(tmp_path, out_root)
    pins = _legacy_sha()
    r = _rob(cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    for name in ROB_APPENDIX:
        assert hashlib.sha256((paper / name).read_bytes()).hexdigest() == pins[name], name
    r2 = _rob(cfg, "--tree", "thesis_report")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert hashlib.sha256((paper / "tab_rob_p1.tex").read_bytes()).hexdigest() == pins["tab_rob_p1.tex"]


@pytest.mark.parametrize("tree", ["thesis_report", BASE])
def test_october_diagnostics_stay_but_completed_draws_clause_tracks_the_data(tmp_path, tree):
    led = tmp_path / "ledgers"
    shutil.copytree(FIX_LEDGERS, led)
    f = led / UNDATED["p1p2"]
    L = json.loads(f.read_text())
    B = L["perm_pvalues"]["B"]
    for k, v in L["perm_pvalues"].items():
        if isinstance(v, dict) and "B_ok" in v:
            v["B_ok"] = B                                # every cell completed: no exception belongs in the note
    f.write_text(json.dumps(L, indent=1))

    out = tmp_path / "out"
    r = _draft(out, "--tree", tree, "--ledger-dir", str(led))
    assert r.returncode == 0, r.stdout + r.stderr       # never a crash on an October fact
    rob = (out / "tab_robustness.tex").read_text()
    flags = [x for x in rob.splitlines() if x.startswith(FLAG)]
    assert flags, rob
    assert any("completed for mathematics" in x for x in flags), flags
    # Historical diagnostic comments stay; the visible note no longer claims incomplete draws.
    assert "completed for" not in rob.split(r"\emph{Notes}:", 1)[1]
    checks = json.loads((out / "NOTE_CHECKS.json").read_text())
    bad = [c for c in checks if not c["holds"]]
    assert bad and all(c["table"] == "tab:robustness" for c in bad), checks
    # nothing else moved: the other two tables are still the fixture/legacy bytes
    pins = _legacy_sha()
    for name in ("tab_main_results.tex", "tab_panels_overview.tex"):
        if tree == BASE:
            assert (out / name).read_bytes() == (FIX_TABLES / name).read_bytes(), name
        else:
            assert hashlib.sha256((out / name).read_bytes()).hexdigest() == pins[name], name


# ---------------------------------------------------------------------------
# R1 M (final-03 audit, 2026-10-18): the M canon has no star-departure cells (F20; the author's ruling of
# 2026-10-15: the paper prints no star-departure robustness), so the robustness ledger has no
# departure_<field> keys. tables_robustness.py keys on the ledger itself: without departure_econ it leaves
# out the two departure rows of each appendix table and the notes' departure sentence, and writes an M FLAG
# comment in place of the October ones. October, and October copied into an M canon, keep every byte.
# ---------------------------------------------------------------------------
M_FLAG = "% R1 M FLAG for the author"
DEP_ROW = "\\REV{Star departure, rule "
DEP_SENT_RX = r"The star-departure rows use the .*?chemistry and mathematics were not screened\. "


def _m_paths_override(tmp, output_root):
    """A paths.yaml selecting a tiny M canon in tmp: CANON.json and the six canon keys under one root, each
    empty (tables_robustness.py reads only output/paper)."""
    root = tmp / "canon_m"
    for k in canon.KEYS:
        (root / k).mkdir(parents=True, exist_ok=True)
    (root / canon.CANON_JSON).write_text(json.dumps({"schema": canon.SCHEMA, "canon": "M",
                                                     "prefix": {k: k for k in canon.KEYS}, "switches": {}}))
    raw = yaml.safe_load(config_file().read_text())
    raw["output"] = str(output_root)
    raw.update({k: str(root / k) for k in canon.KEYS})
    cfg = tmp / "paths_m.yaml"
    cfg.write_text(yaml.safe_dump(raw, allow_unicode=True))
    return cfg


def _drop_departure(paper_dir):
    """The M robustness ledger: the fixture's with the three departure_<field> blocks removed."""
    f = paper_dir / "data_numbers_robustness.json"
    rb = json.loads(f.read_text())
    gone = sorted(k for k in rb if k.startswith("departure_"))
    assert gone == ["departure_chemistry", "departure_econ", "departure_math_stats"], gone
    for k in gone:
        del rb[k]
    f.write_text(json.dumps(rb, indent=1))


def test_tab_rob_m_without_departure_cells_drops_rows_and_sentence(tmp_path):
    ref_root, m_root = tmp_path / "ref", tmp_path / "m"
    _undated_ledgers(ref_root / "paper", FIX_LEDGERS)
    r = _rob(_paths_override(tmp_path, ref_root), "--tree", BASE)
    assert r.returncode == 0, r.stdout + r.stderr
    _undated_ledgers(m_root / "paper", FIX_LEDGERS)
    _drop_departure(m_root / "paper")
    r = _rob(_m_paths_override(tmp_path, m_root), "--tree", BASE)
    assert r.returncode == 0, r.stdout + r.stderr      # no KeyError on the missing departure cells

    for name in ROB_APPENDIX + ("tab_robustness.tex",):
        ref = (ref_root / "paper" / name).read_text()
        got = (m_root / "paper" / name).read_text()
        assert DEP_ROW not in got, name
        flags = [x for x in got.splitlines() if x.startswith("%") and "FLAG" in x]
        assert len(flags) == 1 and flags[0].startswith(M_FLAG), (name, flags)
        assert "2026-10-15" in flags[0] and "October" not in flags[0], flags[0]
        # everything else is the October text: drop the departure rows and sentence, swap the flag line
        want = re.sub(DEP_SENT_RX, "", ref)
        want = "\n".join(flags[0] if x.startswith(FLAG) else x for x in want.splitlines()
                         if not x.startswith(DEP_ROW)) + "\n"
        assert got == want, name
        if name in ROB_APPENDIX:
            assert len(re.findall(DEP_SENT_RX, ref)) == 1 and ref.count(DEP_ROW) == 2, name
            # the author's dash-note sentence stays word for word; the flag names it
            assert "star departure outside economics" in got and "dash note" in flags[0], name
        else:
            assert "(economics only)" in got and "economics only" in flags[0]


def test_tab_rob_october_copied_into_an_m_canon_keeps_every_byte(tmp_path):
    out_root = tmp_path / "out"
    _undated_ledgers(out_root / "paper", FIX_LEDGERS)
    r = _rob(_m_paths_override(tmp_path, out_root), "--tree", BASE)
    assert r.returncode == 0, r.stdout + r.stderr
    for name in ROB_APPENDIX:
        assert (out_root / "paper" / name).read_bytes() == (FIX_TABLES / name).read_bytes(), name


def test_tab_rob_october_without_departure_cells_stops(tmp_path):
    out_root = tmp_path / "out"
    _undated_ledgers(out_root / "paper", FIX_LEDGERS)
    _drop_departure(out_root / "paper")
    r = _rob(_paths_override(tmp_path, out_root), "--tree", BASE)
    assert r.returncode != 0
    assert "October robustness ledger has no star-departure cells" in r.stdout + r.stderr
    assert not (out_root / "paper" / "tab_rob_p1.tex").exists()


# ---------------------------------------------------------------------------
# --paper-dir (review R7 #7): staged 3light reads this run's undated output/paper ledgers, so the M tables
# carry M numbers; on October ledgers the bytes equal the --ledger-dir output
# ---------------------------------------------------------------------------
def _paper_dir_from_fixture(d: pathlib.Path) -> pathlib.Path:
    """The fixture's dated ledgers as output/paper holds them: undated copies, and the merged main ledger
    split back into data_numbers_main.json and data_numbers_carried.json (a disjoint split of its body)."""
    _undated_ledgers(d, FIX_LEDGERS)
    merged = json.loads((FIX_LEDGERS / f"data_numbers_{DATE}.json").read_text(encoding="utf-8"))
    body = [k for k in merged if not k.startswith("_")]
    half = len(body) // 2
    (d / "data_numbers_main.json").write_text(json.dumps(
        {**{k: merged[k] for k in body[:half]}, "_provenance": {"main": "toy"}}, indent=1), encoding="utf-8")
    (d / "data_numbers_carried.json").write_text(json.dumps(
        {**{k: merged[k] for k in body[half:]}, "_provenance": {"carried": "toy"}}, indent=1), encoding="utf-8")
    return d


def test_draft_tables_paper_dir_byte_equal(tmp_path):
    paper = _paper_dir_from_fixture(tmp_path / "paper")
    r = _draft(tmp_path / "pd", "--tree", BASE, "--paper-dir", str(paper))
    assert r.returncode == 0, r.stdout + r.stderr
    r2 = _draft(tmp_path / "ld", "--tree", BASE, "--ledger-dir", str(FIX_LEDGERS))
    assert r2.returncode == 0, r2.stdout + r2.stderr
    for name in DRAFT_NAMES + ("NOTE_CHECKS.json",):
        assert (tmp_path / "pd" / name).read_bytes() == (tmp_path / "ld" / name).read_bytes(), name
    for name in DRAFT_NAMES:
        assert (tmp_path / "pd" / name).read_bytes() == (FIX_TABLES / name).read_bytes(), name
    both = _draft(tmp_path / "both", "--tree", BASE, "--paper-dir", str(paper), "--ledger-dir", str(FIX_LEDGERS))
    assert both.returncode != 0                                 # one ledger source, never two


def test_paper_dir_missing_ledger_fails(tmp_path):
    paper = _paper_dir_from_fixture(tmp_path / "paper")
    (paper / "data_numbers_carried.json").unlink()
    out = tmp_path / "out"
    r = _draft(out, "--tree", BASE, "--paper-dir", str(paper))
    assert r.returncode != 0 and "data_numbers_carried.json" in (r.stdout + r.stderr)
    assert not any(out.glob("tab_*.tex"))                         # never a fall-back to the thesis ledgers


def test_paper_dir_main_carried_clash_fails(tmp_path):
    paper = _paper_dir_from_fixture(tmp_path / "paper")
    m = json.loads((paper / "data_numbers_main.json").read_text())
    c = json.loads((paper / "data_numbers_carried.json").read_text())
    k = next(x for x in m if not x.startswith("_"))
    c[k] = m[k]
    (paper / "data_numbers_carried.json").write_text(json.dumps(c, indent=1))
    out = tmp_path / "out"
    r = _draft(out, "--tree", BASE, "--paper-dir", str(paper))
    assert r.returncode != 0 and k in (r.stdout + r.stderr)
    assert not any(out.glob("tab_*.tex"))


def test_paper_dir_values_are_used(tmp_path):
    paper = _paper_dir_from_fixture(tmp_path / "paper")
    pp = json.loads((paper / "data_numbers_p1p2.json").read_text())
    assert f"{pp['p2_econ']['ate_pp']:.3f}" == "0.195"
    pp["p2_econ"]["ate_pp"] = 0.987
    (paper / "data_numbers_p1p2.json").write_text(json.dumps(pp, indent=1))
    out = tmp_path / "out"
    r = _draft(out, "--tree", BASE, "--paper-dir", str(paper))
    assert r.returncode == 0, r.stdout + r.stderr
    lab = "\\REV{Average post-arrival change (pp per year)}"
    # the label heads two rows (Panel 2 and the Panel 3 A_far row); the p1p2 source comment picks Panel 2
    rows = [x for x in (out / "tab_main_results.tex").read_text().splitlines() if x.startswith(lab) and "p1p2" in x]
    assert len(rows) == 1 and rows[0].split(" & ")[1] == "\\REV{0.987}", rows
    fix = [x for x in (FIX_TABLES / "tab_main_results.tex").read_text().splitlines()
           if x.startswith(lab) and "p1p2" in x]
    assert fix[0].split(" & ")[1] == "\\REV{0.195}"


# ---------------------------------------------------------------------------
# big host only: the real October chain, ledgers included
# ---------------------------------------------------------------------------
def _paper_ledger_stages():
    """run_all.sh's paper stages that build ledgers and gap files, in run_all's order."""
    stages, on = [], False
    for line in (REPO / "analysis" / "run_all.sh").read_text().splitlines():
        if line.startswith('echo "== paper =="'):
            on = True
            continue
        m = re.match(r"run (paper_(?:ledger|gaps)_\w+)\s+(\S+)\s+(\S+)", line) if on else None
        if m:
            exe = sys.executable if m.group(2) == '"$PY"' else shutil.which(m.group(2))
            assert exe, line
            stages.append((m.group(1), [exe, m.group(3).replace("$PP", "analysis/paper")]))
    assert any(s == "paper_ledger_rob" for s, _ in stages), stages
    return stages


@pytest.mark.legacy
def test_all_13_base_tables_from_the_real_chain(tmp_path):
    for stage, cmd in _paper_ledger_stages():
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 0, (stage, r.stdout + r.stderr)
    official = P["output"] / "paper"

    # the house tables, written into a scratch output root so output/paper keeps the default variant
    out_root = tmp_path / "out"
    paper = out_root / "paper"
    paper.mkdir(parents=True)
    for k in ("p1p2", "p3afar", "robustness", "main", "carried"):
        shutil.copyfile(official / f"data_numbers_{k}.json", paper / f"data_numbers_{k}.json")
    cfg = _paths_override(tmp_path, out_root)
    env = dict(os.environ, SAR_PATHS_CONFIG=str(cfg))
    for script, args in (("tables_p3afar.py", []), ("tables_main.py", []), ("tables_p1p2.py", []),
                         ("tables_robustness.py", ["--tree", BASE])):
        r = subprocess.run([sys.executable, str(REPO / "analysis/paper" / script), *args],
                           capture_output=True, text=True, cwd=REPO, env=env)
        assert r.returncode == 0, (script, r.stdout + r.stderr)

    # the draft's three tables read this run's undated ledgers, as staged 3light does (--paper-dir; R7 #7)
    draft_out = tmp_path / "draft"
    r = _draft(draft_out, "--tree", BASE, "--paper-dir", str(official))
    assert r.returncode == 0, r.stdout + r.stderr

    got = {n: (draft_out / n) for n in DRAFT_NAMES}
    for x in sorted(FIX_TABLES.glob("tab_*.tex")):
        if x.name not in got:
            got[x.name] = paper / x.name
    assert len(got) == 13, sorted(got)
    bad = [n for n, p in sorted(got.items()) if p.read_bytes() != (FIX_TABLES / n).read_bytes()]
    assert not bad, bad
