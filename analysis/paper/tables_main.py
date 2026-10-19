#!/usr/bin/env python3
r"""tables_main.py — the two tables whose numbers come from the main / carried / p3afar ledgers:
thesis_report/tables/tab_disciplines.tex (Table "Disciplines at a glance") and
thesis_report/tables/tab_panels_overview.tex (Table "Three intermediate panels").

Both tables were typed by hand and are pinned cell by cell by tools/check_paper.py (section D).
This script makes their numbers generated without touching a word: it takes the thesis's CURRENT
table file as the template, finds each number the sentinel pins with the sentinel's own anchor
(every anchor must match exactly once), replaces only those digits with the ledger value in the
file's own format ({,} grouping), and writes the result to output/paper/. It never writes into the
thesis tree. Checks before writing: (1) outside the replaced spans the output is byte-identical to
the thesis file; (2) re-reading the output with the same anchors gives the ledger values;
(3) no \BOR{}/\BORdel{} span in either file (their counts are asserted unchanged).

Numbers (ledger -> cell):
  tab_disciplines      {d}_events, {d}_persons, {d}_relations.total        (data_numbers_main.json)
  (tab_panels_overview: since the 2026-09-23 sync the thesis's tables/tab_panels_overview.tex is the
   2026-09-13 draft's Table 1, written by draft_2026_09_13_tables.py; the old hand-typed layout this
   script filled is no longer in the thesis, so this script no longer writes that file. The anchors
   of the old layout are kept below in OLD_PANELS_ANCHORS for the record.)

Reads:  output/paper/data_numbers_{main,carried,p3afar}.json (run ledger_main.py, ledger_carried.py,
        ledger_p3afar.py first); <legacy_thesis>/thesis_report/tables/{tab_disciplines,
        tab_panels_overview}.tex (template, read-only)
Writes: output/paper/tab_disciplines.tex
Written 2026-09-23 (cal2026-10, group main_funnel).
Run:    setup/.venv/bin/python analysis/paper/tables_main.py
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
from analysis.lib.paths import load_paths  # noqa: E402

P = load_paths()
OUT = P["output"] / "paper"
TABLES = P["legacy_thesis"] / "thesis_report" / "tables"

# the sentinel's number token (tools/check_paper.py NUM), one capture group per number
NUM = r"([-+]?(?:[0-9]{1,3}(?:(?:\{,\}|,)[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)"


OLD_PANELS_ANCHORS: list = []   # the old tab_panels_overview layout's anchors (not written since 2026-09-23)


def big(n: int) -> str:
    return f"{int(n):,}".replace(",", "{,}")


def anchors(main, carried, p3):
    """file -> list of (anchor regex, [ledger values, one per NUM group]) — the sentinel's anchors."""
    def disc_row(label):
        return (r"\\REV\{" + label + r"\} & \\REV\{" + NUM + r"\} & \\REV\{" + NUM
                + r"\} & \\REV\{" + NUM + r"\}")
    disc = [(disc_row(lab), [main[f"{d}_events"], main[f"{d}_persons"], main[f"{d}_relations"]["total"]])
            for lab, d in (("Economics", "econ"), ("Chemistry", "chem"),
                           (r"Mathematics \\& Statistics", "math"))]
    pr = carried["panel_rows"]
    panels = [
        (r"similarity dose \$\\times\$ post & \\REV\{" + NUM + r"\}", [pr["econ"][0]]),
        (r"first coauthorship with the star & star arrival & \\REV\{" + NUM + r"\}", [pr["econ"][1]]),
        (r"first coauthorship within the pair & star arrival & \\REV\{" + NUM + r"\}", [p3["econ"]["rows"]]),
        (r"Row counts are for economics; the corresponding counts are " + NUM + r" / " + NUM + r" / " + NUM
         + r" for chemistry and " + NUM + r" / " + NUM + r" / " + NUM + r" for mathematics",
         [pr["chem"][0], pr["chem"][1], p3["chemistry"]["rows"],
          pr["math"][0], pr["math"][1], p3["math_stats"]["rows"]]),
    ]
    # 2026-09-23 (REPLACE stage): tab_panels_overview.tex is owned by draft_2026_09_13_tables.py
    # (the thesis now carries the draft's Table 1); `panels` are the old layout's anchors, unused.
    OLD_PANELS_ANCHORS[:] = panels
    return {"tab_disciplines.tex": disc}


def render(text: str, specs):
    """Replace every anchored number with its ledger value. Returns (new_text, changes)."""
    spans = []   # (start, end, new_literal, old_literal)
    for rx, vals in specs:
        hits = list(re.finditer(rx, text))
        assert len(hits) == 1, f"anchor matched {len(hits)} times (must be exactly once): {rx[:70]}"
        m = hits[0]
        assert len(vals) == len(m.groups()), rx[:70]
        for g, v in enumerate(vals, start=1):
            old = m.group(g)
            assert "." not in old and "$" not in old, f"unexpected number format {old!r}"
            spans.append((m.start(g), m.end(g), big(v), old))
    spans.sort()
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), "overlapping anchors"
    out, pos, changes = [], 0, []
    for s, e, new, old in spans:
        out.append(text[pos:s]); out.append(new); pos = e
        if new != old:
            changes.append((old, new))
    out.append(text[pos:])
    return "".join(out), changes


def main() -> int:
    led = {k: json.loads((OUT / f"data_numbers_{k}.json").read_text()) for k in ("main", "carried", "p3afar")}
    specs = anchors(led["main"], led["carried"], led["p3afar"])
    for name, sp in specs.items():
        src = (TABLES / name).read_text(encoding="utf-8")
        new, changes = render(src, sp)
        # (1) outside the numbers, byte-identical to the thesis file
        mask = lambda t: re.sub(NUM, "#", t)  # noqa: E731
        assert mask(new) == mask(src), f"{name}: text outside the number spans changed"
        # (2) the output reads back as the ledger values
        again, still = render(new, sp)
        assert again == new and not still, f"{name}: output does not re-read as the ledger values"
        # (3) no blue-layer span touched
        for tag in (r"\BOR{", r"\BORdel{"):
            assert src.count(tag) == new.count(tag), f"{name}: {tag} count changed"
        (OUT / name).write_text(new, encoding="utf-8")
        print(f"wrote {OUT / name}  ({len(changes)} of {sum(len(v) for _, v in sp)} numbers differ from the thesis file)")
        for old, nw in changes:
            print(f"    {old} -> {nw}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
