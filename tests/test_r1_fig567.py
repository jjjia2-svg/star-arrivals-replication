"""R1 FIG567: the base tree's Figures 5-7 (the 2026-10-03 redraw) from the repo generators.

analysis/paper/fig_p1.py, fig_p2.py and ledger_p3afar.py (which draws through fig_p3_afar.py) take
--tree {thesis_report (default), base_2026_10_11}. The base tree's figures/fig_p1.pdf, fig_p2.pdf and
fig_p3_afar.pdf were drawn on 2026-10-03 by the author's original scripts (verbatim copies in
analysis/paper/_vault_2026-10-03/sec4/, not shipped); on the October ledgers the base_2026_10_11 variant must draw the
same words, in the same order, on the same page size. The default must keep drawing the legacy
thesis_report figures byte for byte once the render date is masked (the B0 comparison rule).

Pins: tests/fixtures/r1_paper/fig567_october.json, read from the printed PDFs (PyMuPDF 1.27.2.2) and from
the original scripts' own asserts, not from the new code. Inputs: the October ledgers in
tests/fixtures/r1_paper/base_tree_2026-10-11/ledgers/. Small-runner tests; the font part (TeX Gyre Pagella
from the pinned TeX layer) runs where that layer is restored, elsewhere the generators are called with the
explicit test fallback, which the record shows.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO / "pipeline" / "aws" / "r1", REPO):
    sys.path.insert(0, str(_p))
import final_stage as fs  # noqa: E402
from analysis.paper import _fig34_style as S  # noqa: E402
from analysis.paper import _fig567_style as F  # noqa: E402
from analysis.paper import fig_p1, fig_p2, fig_p3_afar  # noqa: E402

if not (REPO / "tests/fixtures/r1_paper").is_dir():   # public copy: the manuscript fixtures are not shipped
    pytest.skip("needs the manuscript fixtures in tests/fixtures/r1_paper/ (not shipped)", allow_module_level=True)
FIX = json.loads((REPO / "tests/fixtures/r1_paper/fig567_october.json").read_text(encoding="utf-8"))
LEDGERS = REPO / "tests/fixtures/r1_paper/base_tree_2026-10-11/ledgers"
P1P2 = LEDGERS / "data_numbers_2026-10-23_p1p2.json"
P3 = LEDGERS / "data_numbers_2026-10-23_p3afar.json"
VAULT = REPO / "analysis/paper/_vault_2026-10-03/sec4"
BASE = "base_2026_10_11"
MODS = {"fig_p1": (fig_p1, P1P2), "fig_p2": (fig_p2, P1P2), "fig_p3_afar": (fig_p3_afar, P3)}
#: the Matplotlib the legacy thesis_report PDFs were drawn with (their /Creator), = setup/uv.lock's pin
OCTOBER_MPL = "3.11.1"


def _font_kwargs(tmp_path):
    """The explicit test fallback where the TeX layer is absent; Pagella where it is restored."""
    return {"font_fallback": S.find_pagella() is None, "font_cache": tmp_path / "_fonts"}


def _base(name, tmp_path, ledger=None, sub="out", **kw):
    mod, default_ledger = MODS[name]
    kw = kw or _font_kwargs(tmp_path)
    rec = mod.generate(BASE, ledger or default_ledger, tmp_path / sub, **kw)
    return rec, tmp_path / sub / f"{name}.pdf"


def _pdf(pdf):
    import fitz  # PyMuPDF, in the py layer since W1-PDFTOOLS (config/r1/requirements_final.txt)
    d = fitz.open(str(pdf))
    words = [w[4] for p in d for w in p.get_text("words")]
    fonts = sorted({f[3].split("+", 1)[-1] for p in d for f in p.get_fonts()})
    return len(d), words, fonts, [round(d[0].rect.width, 1), round(d[0].rect.height, 1)]


def _masked_sha(raw: bytes) -> str:
    """sha256 after final_stage.same_file_bytes' mask (/CreationDate, /ModDate, the final startxref)."""
    m = fs._PDF_STARTXREF.sub(b"startxref\nMASKED\n%%EOF\n", fs._PDF_DATE.sub(rb"/\1 (D:MASKED)", raw))
    return hashlib.sha256(m).hexdigest()


# ---- 1. verbatim copies -------------------------------------------------------------------------------
def test_verbatim_copies_unchanged():
    src = (VAULT / "SOURCE.md").read_text(encoding="utf-8")
    assert sorted(p.name for p in VAULT.glob("*.py")) == sorted(FIX["vault_md5"])
    for name, md5 in FIX["vault_md5"].items():
        got = hashlib.md5((VAULT / name).read_bytes()).hexdigest()
        assert got == md5, f"{name}: md5 {got} != the original {md5}"
        assert f"`{name}`" in src and md5 in src, f"SOURCE.md does not record {name} {md5}"
    for name, rec in FIX["base"].items():
        assert rec["md5"] in src, f"SOURCE.md does not record the printed {name}.pdf md5"
    assert "final_figs/sec4" in src


# ---- 2. the base tree's text layer and page size --------------------------------------------------------
@pytest.mark.parametrize("name", sorted(MODS))
def test_base_tree_pdf_text_layer_matches_october(tmp_path, name):
    rec, pdf = _base(name, tmp_path)
    assert pdf.stat().st_size > 5 * 1024
    n, words, fonts, size = _pdf(pdf)
    want = FIX["base"][name]
    assert n == 1
    assert sorted(words) == sorted(want["words"]), (name, words)
    assert words == want["words"], (name, "same words, other stream order", words)
    assert size == want["size_pt"], (name, size)
    # the record's own list of drawn strings gives the same words
    assert sorted(" ".join(rec["texts"]).split()) == sorted(want["words"])
    assert rec["tree"] == BASE and rec["font"]["fallback"] is (S.find_pagella() is None)


def test_base_tree_wording(tmp_path):
    """The 2026-10-03 changes, by name (the fixture holds every word; this says which ones are new)."""
    texts = {n: _base(n, tmp_path, sub=n)[0]["texts"] for n in MODS}
    for n, t in texts.items():
        # one shared x label naming the year before arrival, instead of one "Years since arrival" per panel
        assert [s for s in t if s.startswith("Years since arrival")] == ["Years since arrival (−1 = year before arrival)"]
        assert not any("switchers' dose" in s or "probability" in s for s in t), n
    assert "Change in log output\n(at the doses incumbents hold)" in texts["fig_p1"]
    assert [s.splitlines()[-1] for s in texts["fig_p1"] if "joint placebo" in s] == \
        ["joint placebo p = 0.003", "joint placebo p = 0.856", "joint placebo p = 0.175"]
    assert "zero-dose relations only" in texts["fig_p1"] and "not estimated" not in texts["fig_p1"]
    assert "Change in first-tie rate\nwith the star (pp)" in texts["fig_p2"]
    assert "Change in first-tie\nrate (pp)" in texts["fig_p3_afar"]
    for n in ("fig_p2", "fig_p3_afar"):
        assert "not estimated" in texts[n] and "zero-dose relations only" not in texts[n]
    assert F.ZERO_DOSE_LABEL == S.ZERO_DOSE_TERM + " only"     # Figure 3's key, the same words


def test_pdf_fonts_are_pagella_where_the_tex_layer_is_restored(tmp_path):
    if S.find_pagella() is None:
        if os.environ.get("SAR_HOST", "").strip() == "ec2-r1":
            pytest.fail(f"TeX Gyre Pagella not found under {S.TEXDIR} on the rerun host")
        pytest.skip("the pinned TeX layer is not restored on this runner (font part runs on the big host)")
    for name in MODS:
        rec, pdf = _base(name, tmp_path, sub=name, font_cache=tmp_path / "_fonts")   # no fallback
        assert rec["font"]["family"] == "TeX Gyre Pagella" and rec["font"]["fallback"] is False
        _, words, fonts, size = _pdf(pdf)
        assert words == FIX["base"][name]["words"] and size == FIX["base"][name]["size_pt"]
        assert fonts == ["TeXGyrePagella-Regular"], (name, fonts)    # October: ['Palatino-Roman'] only
        assert FIX["base"][name]["fonts"] == ["Palatino-Roman"]


def test_no_silent_font_fallback(tmp_path):
    empty = tmp_path / "no_tex"
    empty.mkdir()
    for name, (mod, ledger) in MODS.items():
        with pytest.raises(S.FontStop):
            mod.generate(BASE, ledger, tmp_path / f"n_{name}", font_search_dirs=[empty],
                         font_cache=tmp_path / "_fonts")
        assert not (tmp_path / f"n_{name}" / f"{name}.pdf").exists()
        r = subprocess.run([sys.executable, str(REPO / "analysis/paper" / f"{name}.py"), "--tree", BASE,
                            "--ledger", str(ledger), "--out-dir", str(tmp_path / f"c_{name}"),
                            "--font-dir", str(empty)], capture_output=True, text=True, cwd=REPO)
        assert r.returncode == 2 and "STOP" in r.stderr, (name, r.stdout, r.stderr)
        assert not (tmp_path / f"c_{name}" / f"{name}.pdf").exists()


# ---- 3. the October answers are recomputed, not typed ------------------------------------------------------
def test_october_answers_hold_on_the_october_ledgers(tmp_path):
    oa = FIX["october_answers"]
    r1, _ = _base("fig_p1", tmp_path, sub="a")
    assert r1["p_joint_placebo"] == oa["joint_placebo_p"]
    assert r1["zero_dose_only_ell"] == oa["zero_dose_only_ell"] == F.ZERO_DOSE_ONLY_ELL
    r3, _ = _base("fig_p3_afar", tmp_path, sub="c")
    assert [c[:3] for c in r3["clipped"]] == oa["fig_p3_afar_clipped"]
    assert list(fig_p3_afar.CHEM_CLIP) == oa["chem_clip"]
    r2, _ = _base("fig_p2", tmp_path, sub="b")
    assert r2["clipped"] == []
    # the printed p comes from the ledger value, rounded once
    led = json.loads(P1P2.read_text(encoding="utf-8"))
    assert {c: F.fmt_p(led[c]["p_joint_placebo_person"]) for c in oa["joint_placebo_p"]} == oa["joint_placebo_p"]


def test_numbers_follow_a_changed_ledger(tmp_path):
    led = json.loads(P1P2.read_text(encoding="utf-8"))
    led["p1_econ"]["p_joint_placebo_person"] = 0.0004
    led["p1_chemistry"]["p_joint_placebo_person"] = 0.04213
    led["p1_math_stats"]["relations"] = 1234
    led["p2_econ"]["events"] = 99
    toy = tmp_path / "toy_p1p2.json"
    toy.write_text(json.dumps(led), encoding="utf-8")
    r1, pdf1 = _base("fig_p1", tmp_path, ledger=toy, sub="a")
    assert r1["p_joint_placebo"] == {"p1_econ": "<0.001", "p1_chemistry": "0.042", "p1_math_stats": "0.175"}
    _, words, _, _ = _pdf(pdf1)
    assert words.count("<0.001") == 1 and "0.042" in words and "1,234" in words and "0.003" not in words
    r2, pdf2 = _base("fig_p2", tmp_path, ledger=toy, sub="b")
    assert "99" in _pdf(pdf2)[1]
    assert fig_p1.plotted_values(led)["p1_econ"]["p_joint_placebo_person"] == 0.0004


def test_figure7_clip_follows_the_ledger(tmp_path):
    led = json.loads(P3.read_text(encoding="utf-8"))
    led["chemistry"]["horizons_pp"][4]["se_pair"] = 0.2          # year 4 now inside the panel
    toy = tmp_path / "toy_p3.json"
    toy.write_text(json.dumps(led), encoding="utf-8")
    nochk = {**_font_kwargs(tmp_path), "caption_check": False}     # the clip mechanics, apart from the caption
    assert _base("fig_p3_afar", tmp_path, ledger=toy, sub="a", **nochk)[0]["clipped"] == []
    led["chemistry"]["horizons_pp"][0]["se_pair"] = 1.0          # year 0 upper end leaves 1.4
    led["econ"]["horizons_pp"][0]["se_pair"] = 5.0               # economics has no fixed range: never clipped
    toy.write_text(json.dumps(led), encoding="utf-8")
    got = _base("fig_p3_afar", tmp_path, ledger=toy, sub="b", **nochk)[0]["clipped"]
    assert [c[:3] for c in got] == [["chemistry", 0, "upper"]]
    led["chemistry"]["horizons_pp"][4]["est"] = -3.0             # a point estimate outside the range
    toy.write_text(json.dumps(led), encoding="utf-8")
    with pytest.raises(SystemExit, match="STOP fig567"):
        _base("fig_p3_afar", tmp_path, ledger=toy, sub="c", **nochk)
    assert not (tmp_path / "c" / "fig_p3_afar.pdf").exists()


def test_figure7_stops_when_its_arrows_leave_the_caption(tmp_path):
    """review delta-2 #1: the base tree's caption says one arrow marks chemistry's year-four interval (below
    the plot); a ledger that draws other arrows stops the generator and leaves no PDF."""
    led = json.loads(P3.read_text(encoding="utf-8"))
    assert [c[:3] for c in _base("fig_p3_afar", tmp_path, sub="ok")[0]["clipped"]] == fig_p3_afar.CAPTION_ARROWS["october"]
    led["chemistry"]["horizons_pp"][4]["se_pair"] = 0.2                  # no arrow at all
    toy = tmp_path / "toy_p3.json"
    toy.write_text(json.dumps(led), encoding="utf-8")
    with pytest.raises(SystemExit, match="CAPTION_ARROWS"):
        _base("fig_p3_afar", tmp_path, ledger=toy, sub="d")
    assert not (tmp_path / "d" / "fig_p3_afar.pdf").exists()


def test_figure7_caption_arrows_follow_the_canon(tmp_path):
    """R1 final-01: under M chemistry's year-four interval (-1.06, -0.49 pp) stays inside CHEM_CLIP, so Figure 7 draws
    no arrow and the current tree's caption drops the arrow sentence. Under M a figure with no arrow passes and one
    with October's arrow stops; October keeps its arrow."""
    assert fig_p3_afar.CAPTION_ARROWS == {"october": [["chemistry", 4, "lower"]], "M": []}
    led = json.loads(P3.read_text(encoding="utf-8"))
    led["chemistry"]["horizons_pp"][4]["se_pair"] = 0.2                  # no arrow at all
    toy = tmp_path / "toy_p3.json"
    toy.write_text(json.dumps(led), encoding="utf-8")
    kw = _font_kwargs(tmp_path)
    assert _base("fig_p3_afar", tmp_path, ledger=toy, sub="m", mode="M", **kw)[0]["clipped"] == []
    with pytest.raises(SystemExit, match="CAPTION_ARROWS"):              # October's numbers draw the arrow
        _base("fig_p3_afar", tmp_path, sub="m2", mode="M", **kw)
    assert not (tmp_path / "m2" / "fig_p3_afar.pdf").exists()


def test_structural_constants():
    assert F.zero_dose_only_ells() == [-5, -4, 4, 5]
    assert F._runs(F.ZERO_DOSE_ONLY_ELL) == [(-5, -4), (4, 5)]
    assert [F.tick_label(t) for t in range(-6, 6)] == ["", "−5", "", "−3", "", "−1", "0", "1", "2", "3", "4", "5"]
    assert F.fmt_p(0.00049) == "<0.001" and F.fmt_p(0.0005) == "0.001" and F.fmt_p(0.85627104) == "0.856"
    assert fig_p3_afar.FIELDS == [("econ", "Economics"), ("chemistry", "Chemistry"),
                                  ("math_stats", "Mathematics & Statistics")]
    assert F.SAVE_KW == {"metadata": {"CreationDate": None}}


# ---- 4. switch-off: the default still draws the legacy thesis_report figures ------------------------------
@pytest.mark.parametrize("name", sorted(MODS))
def test_default_tree_draws_the_thesis_report_figure(tmp_path, name):
    import matplotlib
    assert matplotlib.__version__ == OCTOBER_MPL, (
        f"Matplotlib {matplotlib.__version__}: the thesis_report pins were drawn with {OCTOBER_MPL} (setup/uv.lock)")
    _, ledger = MODS[name]
    out = tmp_path / "default"
    r = subprocess.run([sys.executable, str(REPO / "analysis/paper" / f"{name}.py"), "--ledger", str(ledger),
                        "--out-dir", str(out)], capture_output=True, text=True, cwd=REPO,
                       env={**os.environ, "MPLBACKEND": "Agg"})
    assert r.returncode == 0, (r.stdout, r.stderr)
    raw = (out / f"{name}.pdf").read_bytes()
    want = FIX["thesis_report"][name]
    assert _masked_sha(raw) == want["masked_sha256"], name
    n, words, fonts, size = _pdf(out / f"{name}.pdf")
    assert words == want["words"] and size == want["size_pt"] and fonts == want["fonts"] == ["DejaVuSans"]


def test_ledger_p3afar_draws_through_fig_p3_afar():
    """ledger_p3afar.py builds the ledger and hands it to fig_p3_afar.draw with --tree; it no longer draws."""
    src = (REPO / "analysis/paper/ledger_p3afar.py").read_text(encoding="utf-8")
    assert "fig_p3_afar.draw(led, ARGS.tree, OUT_FIG" in src
    assert "plt." not in src and "matplotlib" not in src.split('"""', 2)[2]
    assert re.search(r'add_argument\("--tree", choices=fig_p3_afar\.TREES, default="thesis_report"', src)
    assert src.index("fig_p3_afar.draw(") < src.index("json.dump(led, open(OUT_JSON")
    # the drawing lines moved unchanged (the old inline ones, as of r1-code 5e7633b, are all in draw_thesis_report)
    fig = (REPO / "analysis/paper/fig_p3_afar.py").read_text(encoding="utf-8")
    for line in ('ax.errorbar(xs, ys, yerr=[1.96 * v for v in ses], fmt="o", color="black", ms=3.5, capsize=2.5, lw=0.9)',
                 "ax.set_title(f\"{title}\\n{d['pairs']:,} pairs, {d['events_with_pairs']} events\", fontsize=8)",
                 'axes[0, 0].set_ylabel("Change in yearly first-tie\\nprobability (pp)", fontsize=8)',
                 'fig, axes = plt.subplots(2, 3, figsize=(6.6, 4.9))'):
        assert line in fig, line


def test_no_system_font_and_no_literal_october_root():
    for mod in (F, fig_p1, fig_p2, fig_p3_afar):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert "/System/Library/Fonts" not in src and "Palatino.ttc" not in src
        assert "cal2026-10" not in src and "data/frames" not in src
        assert "/Users/" not in src
