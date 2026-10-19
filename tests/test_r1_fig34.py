"""R1 N9 (unit W1-FIG34): Figures 3 and 4 as data-driven generators.

analysis/paper/fig_compare_years.py (Figure 3, the vault's figA.py) and fig_comparison_pools.py
(Figure 4, figB.py) read the economics arrivals from the carried ledger (events_by_school_econ) instead
of the October constants, and write the figure PDF plus a figure-data JSON into output/paper. The
October drawn structure is pinned in tests/fixtures/r1_paper/fig34_october.json, whose values come from
the vault scripts' own asserts and from the printed base-tree PDFs (not from the new code).

Small-runner tests. The font part (TeX Gyre Pagella from the pinned TeX layer) runs only where that
layer is restored; elsewhere the generators are called with the explicit test fallback, which the JSON
records - the final job never passes it, and test_no_silent_font_fallback proves the default STOPs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import analysis.paper.fig_compare_years as FA  # noqa: E402
import analysis.paper.fig_comparison_pools as FB  # noqa: E402
from analysis.paper import _fig34_style as S  # noqa: E402
from analysis.lib.paths import load_paths  # noqa: E402

if not (REPO / "tests/fixtures/r1_paper").is_dir():   # public copy: the manuscript fixtures are not shipped
    pytest.skip("needs the manuscript fixtures in tests/fixtures/r1_paper/ (not shipped)", allow_module_level=True)
FIX = json.loads((REPO / "tests/fixtures/r1_paper/fig34_october.json").read_text(encoding="utf-8"))
VAULT = REPO / "analysis/paper/_vault_2026-10-03"
#: md5 of the verbatim copies = the original drawing scripts fig{A,B}.py (third version, 2026-10-03; not shipped)
VAULT_MD5 = {"figA.py": "b940fce848b102fbe562e21af50e4629", "figB.py": "09fc9de8c686570b88e9fe4894414fd8"}
#: md5 of the printed PDFs those scripts made (= the 2026-10-11 base tree's figures)
PDF_MD5 = {"fig_compare_years.pdf": "9fd5a514076d0ef92d8fcc3b02d230ad",
           "fig_comparison_pools.pdf": "b8e30a1494d9e599cd3960d2d42cce14"}
OCTOBER_EVENTS_CSV = REPO / "data/cal2026-10/events_econ_cal2026-10.csv"


def _ledger(tmp_path, events_by_school, name="data_numbers_carried.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"_provenance": {}, "events_by_school_econ": events_by_school}), encoding="utf-8")
    return p


def _font_kwargs(tmp_path):
    """The explicit test fallback where the TeX layer is absent; Pagella where it is restored."""
    return {"font_fallback": S.find_pagella() is None, "font_cache": tmp_path / "_fonts"}


def _gen(mod, tmp_path, events_by_school, sub):
    out = tmp_path / sub
    data = mod.generate(ledger=_ledger(tmp_path, events_by_school, f"ledger_{sub}.json"), out_dir=out,
                        **_font_kwargs(tmp_path))
    on_disk = json.loads((out / f"{mod.NAME}.json").read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(data, ensure_ascii=False)), "returned and written JSON differ"
    return on_disk, out / f"{mod.NAME}.pdf"


def _sub(full: dict, want: dict, where: str):
    """Every key the fixture pins equals the generated value."""
    for k, v in want.items():
        assert k in full, f"{where}: key {k!r} missing"
        assert full[k] == v, f"{where}.{k}: generated {full[k]!r} != October {v!r}"


# ---- 1. the arrivals come from the ledger ---------------------------------------------------------
def test_arrivals_come_from_the_ledger(tmp_path):
    # the fixture's events_by_school_econ is the October carried-ledger value (ledger_carried group 8)
    rows = list(csv.DictReader(open(OCTOBER_EVENTS_CSV, newline="", encoding="utf-8")))
    by_school: dict = {}
    for r in rows:
        by_school.setdefault(r["school"], []).append(int(r["arrival_year"]))
    assert {k: sorted(v) for k, v in sorted(by_school.items())} == FIX["events_by_school_econ"]
    arr = S.load_arrivals(_ledger(tmp_path, FIX["events_by_school_econ"]))
    assert {y: arr[y] for y in range(2016, 2022)} == {2016: 6, 2017: 13, 2018: 10, 2019: 8, 2020: 3, 2021: 4}
    assert {str(y): arr[y] for y in range(2016, 2022)} == FIX["arrivals_2016_2021"]
    assert sum(arr.values()) == 113 and all(isinstance(y, int) for y in arr)
    # both generators read output/paper/data_numbers_carried.json by default (paths via config only)
    want = load_paths()["output"] / "paper" / "data_numbers_carried.json"
    assert FA.LEDGER == want and FB.LEDGER == want
    # a ledger without the key is refused, not defaulted
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"_provenance": {}}), encoding="utf-8")
    with pytest.raises(SystemExit):
        S.load_arrivals(bad)


# ---- 2. October structure ---------------------------------------------------------------------------
def test_october_drawn_structure_equals_fixture(tmp_path):
    ebs = FIX["events_by_school_econ"]
    ja, _ = _gen(FA, tmp_path, ebs, "a")
    jb, _ = _gen(FB, tmp_path, ebs, "b")
    _sub(ja, FIX["fig_compare_years"], "fig_compare_years")
    _sub(jb, FIX["fig_comparison_pools"], "fig_comparison_pools")
    # the brief's headline structure, spelled out
    assert ja["open_heads"] == [2011, 2012, 2020, 2021]
    assert [y for y, s in jb["cells"]["M1_pos"].items() if s == "none"] == ["2011", "2012", "2020", "2021"]
    assert [y for y, s in jb["cells"]["M23"].items() if s == "not_reported"] == ["2011", "2012", "2013", "2014"]
    assert [y for y, s in jb["cells"]["M23"].items() if s == "no_estimate"] == ["2021"]
    assert [jb["pools"]["M1_pos"][str(t)]["n_events"] for t in (2016, 2017, 2018, 2019)] == [34, 21, 11, 3]
    assert [jb["pools"]["M23"][str(t)]["n_events"] for t in range(2016, 2021)] == [38, 25, 15, 7, 4]
    # Figure 3's open heads are exactly Figure 4's Model 1 'none' cells (one rule, two figures)
    assert ja["open_heads"] == [int(y) for y, s in jb["cells"]["M1_pos"].items() if s == "none"]
    # no count is drawn (figB's PINNED rule): no drawn string carries a digit other than years/model names
    for s in ja["texts"] + jb["texts"]:
        for t in s.split():
            if any(ch.isdigit() for ch in t):
                assert re.fullmatch(r"20(1[1-9]|2[01])|−?[0-5]|1|2–3", t), (s, t)
    assert jb["pinned"] is None


# ---- 3. a different ledger moves the counts and states, and no October assert fires -----------------
def test_counts_follow_a_changed_ledger(tmp_path):
    toy = {}
    for school, years in FIX["events_by_school_econ"].items():
        ys = [y for y in years if y != 2020] + [y for y in years if y == 2017]  # no 2020, twice 2017
        toy[school] = sorted(ys)
    arr = S.load_arrivals(_ledger(tmp_path, toy))
    assert arr.get(2020, 0) == 0 and arr[2017] == 26
    ja, _ = _gen(FA, tmp_path, toy, "ta")
    jb, _ = _gen(FB, tmp_path, toy, "tb")
    m1 = jb["pools"]["M1_pos"]
    assert {t: (m1[t]["arrival_years"], m1[t]["n_events"]) for t in m1} == {
        "2011": ([], 0), "2012": ([], 0), "2013": ([2018], 10), "2014": ([2017, 2018, 2019], 44),
        "2016": ([2017, 2018, 2019], 44), "2017": ([2018, 2019], 18), "2018": ([2019], 8),
        "2019": ([], 0), "2020": ([], 0), "2021": ([], 0)}
    m23 = jb["pools"]["M23"]
    assert {t: (m23[t]["arrival_years"], m23[t]["n_events"]) for t in m23} == {
        "2016": ([2017, 2018, 2019, 2021], 48), "2017": ([2018, 2019, 2021], 22), "2018": ([2019, 2021], 12),
        "2019": ([2021], 4), "2020": ([2021], 4), "2021": ([], 0)}
    assert [y for y, s in jb["cells"]["M1_pos"].items() if s == "none"] == ["2011", "2012", "2019", "2020", "2021"]
    assert ja["open_heads"] == [2011, 2012, 2019, 2020, 2021]
    # structural rules still hold: the window rule (Model 1 zero-dose used every year), 2021 has no
    # Models 2-3 coefficient, the placebos keep their pairing and are not reported for Models 2-3
    assert set(jb["cells"]["M1_zero"].values()) == {"used"}
    assert jb["cells"]["M23"]["2021"] == "no_estimate"
    assert [y for y, s in jb["cells"]["M23"].items() if s == "not_reported"] == ["2011", "2012", "2013", "2014"]
    assert jb["zero_dose_ranges"] == FIX["fig_comparison_pools"]["zero_dose_ranges"]
    assert {t: m1[t]["paired_effect"] for t in ("2011", "2012", "2013", "2014")} == \
        {"2011": 2019, "2012": 2018, "2013": 2017, "2014": 2016}
    assert ja["rows"] == FIX["fig_compare_years"]["rows"]
    assert ja["ell_labels"] == FIX["fig_compare_years"]["ell_labels"]
    # the changed ledger really changed the figure (the October structure is not hard-wired)
    assert jb["cells"] != FIX["fig_comparison_pools"]["cells"]
    assert ja["arrows"] != FIX["fig_compare_years"]["arrows"]


def test_pools_ignore_years_outside_the_windows(tmp_path):
    """Arrivals in or before 2016, or after the Models 2-3 window (2022+), never enter a pool: adding
    them leaves both figures unchanged."""
    extra = {k: list(v) for k, v in FIX["events_by_school_econ"].items()}
    extra["monash"] = sorted(extra["monash"] + [1990, 2015, 2016, 2016, 2022, 2030])
    ja, _ = _gen(FA, tmp_path, extra, "xa")
    jb, _ = _gen(FB, tmp_path, extra, "xb")
    _sub(ja, FIX["fig_compare_years"], "fig_compare_years")
    _sub(jb, FIX["fig_comparison_pools"], "fig_comparison_pools")


# ---- 4. verbatim copies -------------------------------------------------------------------------------
def test_verbatim_copies_unchanged():
    src = (VAULT / "SOURCE.md").read_text(encoding="utf-8")
    for name, md5 in VAULT_MD5.items():
        got = hashlib.md5((VAULT / name).read_bytes()).hexdigest()
        assert got == md5, f"{name}: md5 {got} != the vault original {md5}"
        assert f"`{name}`" in src and md5 in src, f"SOURCE.md does not record {name} {md5}"
    for name, md5 in PDF_MD5.items():
        assert md5 in src and name in src, f"SOURCE.md does not record the printed {name} md5 {md5}"
    assert "图_第三版" in src and "final_figs" in src  # names the source and the rejected candidate


# ---- 5. the PDF text layer ----------------------------------------------------------------------------
def _pdf_words(pdf):
    import fitz  # PyMuPDF, in the py layer since W1-PDFTOOLS (config/r1/requirements_final.txt)
    d = fitz.open(str(pdf))
    words = [w[4] for p in d for w in p.get_text("words")]
    fonts = sorted({f[3].split("+", 1)[-1] for p in d for f in p.get_fonts()})
    size = [round(d[0].rect.width, 1), round(d[0].rect.height, 1)]
    return len(d), words, fonts, size


def test_pdf_text_layer_matches_october(tmp_path):
    ebs = FIX["events_by_school_econ"]
    for mod, sub in ((FA, "pa"), (FB, "pb")):
        js, pdf = _gen(mod, tmp_path, ebs, sub)
        assert pdf.stat().st_size > 5 * 1024, f"{pdf.name} is {pdf.stat().st_size} bytes"
        n, words, fonts, size = _pdf_words(pdf)
        assert n == 1
        assert sorted(words) == sorted(FIX["pdf_words"][mod.NAME]), (mod.NAME, words)
        assert size == FIX["pdf_size_pt"][mod.NAME], (mod.NAME, size)
        # the JSON's own record of the drawn strings gives the same words
        assert sorted(" ".join(js["texts"]).split()) == sorted(FIX["pdf_words"][mod.NAME])


def test_pdf_fonts_are_pagella_where_the_tex_layer_is_restored(tmp_path):
    """The font part: TeX Gyre Pagella (Palatino clone, mathpazo in the thesis body) from the pinned
    TeX layer, all faces embedded; italic and bold faces present where October had them."""
    if S.find_pagella() is None:
        if os.environ.get("SAR_HOST", "").strip() == "ec2-r1":
            pytest.fail(f"TeX Gyre Pagella not found under {S.TEXDIR} on the rerun host")
        pytest.skip("the pinned TeX layer is not restored on this runner (font part runs on the big host)")
    ebs = FIX["events_by_school_econ"]
    want_faces = {"fig_compare_years": {"Regular", "Italic"},
                  "fig_comparison_pools": {"Regular", "Bold", "Italic"}}
    for mod, sub in ((FA, "fa"), (FB, "fb")):
        out = tmp_path / sub
        js = mod.generate(ledger=_ledger(tmp_path, ebs, f"l_{sub}.json"), out_dir=out,
                          font_cache=tmp_path / "_fonts")          # no fallback: the final job's call
        assert js["font"]["family"] == "TeX Gyre Pagella" and js["font"]["fallback"] is False
        _, words, fonts, _ = _pdf_words(out / f"{mod.NAME}.pdf")
        assert sorted(words) == sorted(FIX["pdf_words"][mod.NAME])
        assert all(f.startswith("TeXGyrePagella") for f in fonts), fonts
        faces = {f.split("-", 1)[1] if "-" in f else "Regular" for f in fonts}
        assert faces == want_faces[mod.NAME], (mod.NAME, fonts)


def test_no_silent_font_fallback(tmp_path):
    """Without the TeX layer and without the explicit test flag, the generators STOP."""
    empty = tmp_path / "no_tex"
    empty.mkdir()
    assert S.find_pagella(search_dirs=[empty]) is None
    with pytest.raises(S.FontStop):
        S.use_font(font_fallback=False, search_dirs=[empty], cache=tmp_path / "_fonts")
    for mod in (FA, FB):
        with pytest.raises(S.FontStop):
            mod.generate(ledger=_ledger(tmp_path, FIX["events_by_school_econ"], f"n_{mod.NAME}.json"),
                         out_dir=tmp_path / f"n_{mod.NAME}", font_search_dirs=[empty],
                         font_cache=tmp_path / "_fonts")
        assert not (tmp_path / f"n_{mod.NAME}" / f"{mod.NAME}.pdf").exists()
    # the CLI exits non-zero with a STOP line instead of drawing in DejaVu
    with pytest.raises(SystemExit) as e:
        FB.main(["--ledger", str(_ledger(tmp_path, FIX["events_by_school_econ"], "cli.json")),
                 "--out-dir", str(tmp_path / "cli"), "--font-dir", str(empty)])
    assert e.value.code == 2


def test_tex_layer_constant_matches_the_env_build():
    """S.TEXDIR is the TeX layer's install root in build_env.sh, whose collection-fontsrecommended
    carries tex-gyre (texgyrepagella-*.otf)."""
    env = (REPO / "pipeline/aws/r1/build_env.sh").read_text(encoding="utf-8")
    assert f"TEXDIR {S.TEXDIR}" in env
    assert "collection-fontsrecommended" in env
    assert set(S.PAGELLA_FILES.values()) == {"texgyrepagella-regular.otf", "texgyrepagella-italic.otf",
                                             "texgyrepagella-bold.otf", "texgyrepagella-bolditalic.otf"}


def test_shared_geometry_puts_every_year_at_one_x():
    """Replaces figA.py reading figB.py's source by regex: one geometry module, same x per year."""
    cs = [S.centre(y) for y in range(2011, 2022)]
    assert all(abs((b - a) - S.CW) < 1e-5 for a, b in zip(cs, cs[1:]))
    assert abs(S.GAP - S.CW) < 1e-5
    # the vault's constants, unchanged
    assert (S.W, S.X0, S.X1, S.GAP, S.PAD) == (6.3, 1.97, 6.3 - 0.03, 0.390909, 0.028)
    assert S.col_x(2016) - S.GAP_X1 < 1e-9 and abs(S.col_x(2014) + S.CW - S.GAP_X0) < 1e-9
    assert S.RX == S.GAP_X1 - S.PAD / 2


def test_no_caption_txt_and_no_literal_october_root():
    for mod in (FA, FB):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert "caption.txt" not in src
        assert "cal2026-10" not in src and "data/frames" not in src
    style = pathlib.Path(S.__file__).read_text(encoding="utf-8")
    assert "cal2026-10" not in style and "/System/Library/Fonts" not in style
