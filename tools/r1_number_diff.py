#!/usr/bin/env python3
"""R1 F24' - the new-vs-October number table: two installed ledger sets side by side, leaf by leaf.

  r1_number_diff.py --old DIR [--old-date 2026-10-23] --new DIR --new-date D --out DIR [--printed FILE]

Old side: the October installed ledgers (F1 upload r1/ref/october/ledgers_base_tree, synced to
/data/ref/october/ledgers_base_tree). New side: M's ledgers after the final job's scratch
`install.py ledgers`, i.e. the same file transform (main + carried merged; the rest byte copies).

What it does
* Pairs the ten ledgers by suffix: data_numbers_<date><suffix>.json for the suffixes in SUFFIXES.
  Only files of the selected date are read; another date's file in the same folder (e.g.
  data_numbers_2026-08-16.json) is ignored. A file of the selected date with an unknown suffix is
  "unexpected" and is not read.
* Flattens every non-underscore key, at every level, to a dotted / indexed path (a.b[0].c); keys
  starting with "_" (_provenance, _source, _october, _diff_vs_october, _inputs, ...) never appear.
* Writes OUT/ledger_diff.csv with exactly the columns in HEADER, every leaf of both sides:
    status        unchanged | changed | added | dropped   (exact JSON equality: 1 and 1.0 differ)
    same_at_3dp   both numeric: "true"/"false" (the two values print the same at 3 dp), else ""
    sign_change   both numeric: "true" when one is < 0 and the other > 0, else "false"; else ""
    p_crosses_005 a p-value key (name p, p_*, *_p, or containing "pvalue") with both sides numeric:
                  "true" when exactly one side is < 0.05; else "false"; any other key ""
    printed       only from --printed (the sentinel's key list): "true"/"false"; without it "" -
                  never guessed
* Writes OUT/number_table.md: counts per ledger, then the sign changes and p crossings, then the
  changed/added/dropped rows grouped by ledger (flagged rows first). Dropped leaves of the cells the
  plan cut (CUT_BY_PLAN: dosebin3, P3dose3) carry the note "cut by plan (F19)".

What it does not do (C10, F12 = M_rerun = no): no attribution to switches, no reruns, no old79/new37
split rows. A ledger key containing old79 or new37 (any level, any case) is refused: exit 2 and
nothing is written.

--printed FILE: a text file with one entry per line ("<ledger>\\t<key>" or "<key>" for any ledger;
blank lines and "#" lines skipped), or a JSON list of such strings, or a JSON object
{ledger: [key, ...]}. An entry marks its key and every leaf below it (key.x, key[0]).

Exit 0; exit 2 on an unpaired ledger (its leaves are still written as added/dropped, with a WARN),
an unexpected file, a missing folder, or a C10 key.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import json
import pathlib
import re
import sys

HEADER = ["ledger", "key", "old", "new", "status", "same_at_3dp", "sign_change", "p_crosses_005", "printed"]
#: tools/repin_thesis_2026-10/install.py (not shipped): main (+ carried merged), COPIED, then GAPS
SUFFIXES = ("", "_p1p2", "_p3afar", "_robustness", "_funnel", "_gaps_zenou", "_gaps_zero_dose",
            "_gaps_switchers", "_gaps_switchers_p1p2", "_gaps_toy")
CUT_BY_PLAN = ("dosebin3", "P3dose3")
CUT_NOTE = "cut by plan (F19)"
FORBIDDEN = ("old79", "new37")
STATUS_RANK = {"changed": 0, "added": 1, "dropped": 2}
MD_WIDTH = 60


def ledger_name(suffix: str) -> str:
    return suffix[1:] if suffix else "main"


def file_name(date: str, suffix: str) -> str:
    return f"data_numbers_{date}{suffix}.json"


def find_ledgers(d: pathlib.Path, date: str) -> tuple[dict, list]:
    """{suffix: path} for the files of `date`, and the unexpected names of that date (not read)."""
    expected = {file_name(date, s): s for s in SUFFIXES}
    found, unexpected = {}, []
    for p in sorted(d.iterdir()):
        if not p.is_file() or not fnmatch.fnmatchcase(p.name, f"data_numbers_{date}*.json"):
            continue
        if p.name in expected:
            found[expected[p.name]] = p
        else:
            unexpected.append(p.name)
    return found, unexpected


def flatten(obj) -> dict:
    """Leaf path -> value; keys starting with '_' are skipped at every level. An empty ledger (and an absent
    one, which run() reads as {}) has no leaves: an empty container is a leaf only below the root, where it
    has a key (t-0023: the root used to come out as a leaf '' = {}, an 'added' row on the missing side)."""
    out: dict = {}

    def walk(v, path):
        if isinstance(v, dict) and v:
            for k, x in v.items():
                if str(k).startswith("_"):
                    continue
                walk(x, f"{path}.{k}" if path else str(k))
        elif isinstance(v, list) and v:
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
        else:
            out[path] = v

    if isinstance(obj, (dict, list)) and not obj:
        return out
    walk(obj, "")
    return out


def forbidden_keys(obj, path="") -> list:
    """Every key (underscore keys included) whose name contains old79/new37, case-insensitive."""
    hits = []
    if isinstance(obj, dict):
        for k, x in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if any(f in str(k).lower() for f in FORBIDDEN):
                hits.append(p)
            hits += forbidden_keys(x, p)
    elif isinstance(obj, list):
        for i, x in enumerate(obj):
            hits += forbidden_keys(x, f"{path}[{i}]")
    return hits


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _canon(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _cell(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _f3(x) -> str:
    s = f"{x:.3f}"
    return "0.000" if s == "-0.000" else s


def is_p_key(key: str) -> bool:
    name = re.sub(r"(\[\d+\])+$", "", key).rsplit(".", 1)[-1].lower()
    return name == "p" or name.startswith("p_") or name.endswith("_p") or "pvalue" in name


def _tf(b: bool) -> str:
    return "true" if b else "false"


def load_printed(path: pathlib.Path) -> list:
    """[(ledger or None, key)] from a text list, a JSON list or a JSON {ledger: [keys]}."""
    text = path.read_text(encoding="utf-8")

    def entry(s: str):
        s = s.strip("\r\n")
        if "\t" in s:
            led, key = s.split("\t", 1)
            return led.strip(), key.strip()
        return None, s.strip()

    if path.suffix.lower() == ".json":
        obj = json.loads(text)
        if isinstance(obj, dict):
            return [(led, str(k)) for led, keys in obj.items() for k in keys]
        if isinstance(obj, list):
            return [entry(str(s)) for s in obj]
        raise SystemExit(f"--printed {path}: expected a JSON list or object")
    return [entry(line) for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def _printed(ledger: str, key: str, entries) -> bool:
    return any((led is None or led == ledger) and (key == k or key.startswith(k + ".") or key.startswith(k + "["))
               for led, k in entries)


def compare(ledger: str, old: dict, new: dict, entries=None) -> list:
    rows = []
    for key in list(old) + [k for k in new if k not in old]:
        has_o, has_n = key in old, key in new
        o, n = old.get(key), new.get(key)
        if has_o and has_n:
            status = "unchanged" if _canon(o) == _canon(n) else "changed"
        else:
            status = "dropped" if has_o else "added"
        s3 = sg = pc = ""
        if has_o and has_n and _num(o) and _num(n):
            s3 = _tf(_f3(o) == _f3(n))
            sg = _tf((o < 0 < n) or (n < 0 < o))
            if is_p_key(key):
                pc = _tf((o < 0.05) != (n < 0.05))
        pr = "" if entries is None else _tf(_printed(ledger, key, entries))
        rows.append({"ledger": ledger, "key": key, "old": _cell(o) if has_o else "", "new": _cell(n) if has_n else "",
                     "status": status, "same_at_3dp": s3, "sign_change": sg, "p_crosses_005": pc, "printed": pr})
    return rows


def _md_val(s: str) -> str:
    s = s.replace("|", "\\|").replace("\n", " ")
    return s if len(s) <= MD_WIDTH else s[:MD_WIDTH - 3] + "..."


def _flagged(r) -> bool:
    return r["sign_change"] == "true" or r["p_crosses_005"] == "true"


def _note(r) -> str:
    return CUT_NOTE if r["status"] == "dropped" and any(c in r["key"] for c in CUT_BY_PLAN) else ""


def render_md(rows: list, warnings: list, meta: dict) -> str:
    L = ["# New vs October: ledger numbers", "",
         f"Old: `{meta['old']}` (date {meta['old_date']}). New: `{meta['new']}` (date {meta['new_date']}).",
         "Two existing result sets side by side, leaf by leaf; no attribution to switches and no reruns "
         "(F12 = M_rerun = no, C10). Equality is exact; `same at 3 dp` says whether the two values print alike.",
         f"Printed column: {'from ' + meta['printed'] if meta['printed'] else 'not given (empty, never guessed)'}.", ""]
    if warnings:
        L += ["## Warnings", ""] + [f"- {w}" for w in warnings] + [""]
    L += ["## Counts", "",
          "| ledger | leaves | unchanged | changed | added | dropped | changed, same at 3 dp | sign changes "
          "| p crosses 0.05 | printed and not unchanged |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    tot = [0] * 9
    for led in [ledger_name(s) for s in SUFFIXES]:
        rs = [r for r in rows if r["ledger"] == led]
        c = [len(rs)] + [sum(r["status"] == s for r in rs) for s in ("unchanged", "changed", "added", "dropped")] + [
            sum(r["status"] == "changed" and r["same_at_3dp"] == "true" for r in rs),
            sum(r["sign_change"] == "true" for r in rs), sum(r["p_crosses_005"] == "true" for r in rs),
            sum(r["printed"] == "true" and r["status"] != "unchanged" for r in rs)]
        tot = [a + b for a, b in zip(tot, c)]
        L.append(f"| {led} | " + " | ".join(str(x) for x in c) + " |")
    L.append("| total | " + " | ".join(str(x) for x in tot) + " |")
    cut = sum(bool(_note(r)) for r in rows)
    if cut:
        L += ["", f"{cut} dropped leaves belong to cells the plan cut ({CUT_NOTE}), not lost."]
    flagged = [r for r in rows if _flagged(r)]
    L += ["", "## Sign changes and p crossings", ""]
    if flagged:
        L += ["| ledger | key | old | new | sign change | p crosses 0.05 | printed |", "|---|---|---|---|---|---|---|"]
        L += [f"| {r['ledger']} | {_md_val(r['key'])} | {_md_val(r['old'])} | {_md_val(r['new'])} | "
              f"{r['sign_change']} | {r['p_crosses_005']} | {r['printed']} |" for r in flagged]
    else:
        L.append("None.")
    L += ["", "## Changed, added and dropped, by ledger", ""]
    diffs = [r for r in rows if r["status"] != "unchanged"]
    if not diffs:
        L.append("No changed, added or dropped leaves.")
    for led in [ledger_name(s) for s in SUFFIXES]:
        rs = [r for r in diffs if r["ledger"] == led]
        if not rs:
            continue
        rs = sorted(rs, key=lambda r: (not _flagged(r), STATUS_RANK[r["status"]]))   # stable: ledger order kept
        L += [f"### {led}", "", "| key | old | new | status | same at 3 dp | sign change | p crosses 0.05 | printed | note |",
              "|---|---|---|---|---|---|---|---|---|"]
        L += [f"| {_md_val(r['key'])} | {_md_val(r['old'])} | {_md_val(r['new'])} | {r['status']} | {r['same_at_3dp']} | "
              f"{r['sign_change']} | {r['p_crosses_005']} | {r['printed']} | {_note(r)} |" for r in rs]
        L.append("")
    return "\n".join(L).rstrip("\n") + "\n"


def run(old: pathlib.Path, old_date: str, new: pathlib.Path, new_date: str, out: pathlib.Path,
        printed: pathlib.Path | None = None) -> int:
    for side, d in (("old", old), ("new", new)):
        if not d.is_dir():
            print(f"ERROR: --{side} {d} is not a folder", file=sys.stderr)
            return 2
    out.mkdir(parents=True, exist_ok=True)
    for name in ("ledger_diff.csv", "number_table.md"):       # this run's results only
        if (out / name).exists():
            (out / name).unlink()
    found_o, unexp_o = find_ledgers(old, old_date)
    found_n, unexp_n = find_ledgers(new, new_date)
    warnings, bad = [], False
    for side, names in (("old", unexp_o), ("new", unexp_n)):
        for n in names:
            warnings.append(f"WARN: unexpected file on the {side} side, not read: {n}")
            bad = True
    data = {}
    for side, found in (("old", found_o), ("new", found_n)):
        for suf, p in found.items():
            data[side, suf] = json.loads(p.read_text(encoding="utf-8"))
    hits = [f"{side}:{ledger_name(suf)}:{k}" for (side, suf), obj in data.items() for k in forbidden_keys(obj)]
    if hits:
        for h in hits:
            print(f"REFUSED (C10, no old79/new37 rows): {h}", file=sys.stderr)
        return 2
    entries = load_printed(printed) if printed else None
    rows = []
    for suf in SUFFIXES:
        led = ledger_name(suf)
        o, n = ("old", suf) in data, ("new", suf) in data
        if not (o and n):
            missing = " and ".join(s for s, here in (("old", o), ("new", n)) if not here)
            warnings.append(f"WARN: ledger {led} ({file_name(old_date if not o else new_date, suf)}) missing on the "
                            f"{missing} side; its leaves are listed as {'dropped' if o else 'added' if n else 'absent'}")
            bad = True
        rows += compare(led, flatten(data.get(("old", suf), {})), flatten(data.get(("new", suf), {})), entries)
    with open(out / "ledger_diff.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    meta = {"old": str(old), "old_date": old_date, "new": str(new), "new_date": new_date,
            "printed": str(printed) if printed else ""}
    (out / "number_table.md").write_text(render_md(rows, warnings, meta), encoding="utf-8")
    for wl in warnings:
        print(wl, file=sys.stderr)
    counts = {s: sum(r["status"] == s for r in rows) for s in ("unchanged", "changed", "added", "dropped")}
    print(f"{len(rows)} leaves: " + ", ".join(f"{v} {k}" for k, v in counts.items()) + f" -> {out}")
    return 2 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    ap.add_argument("--old", required=True, type=pathlib.Path)
    ap.add_argument("--old-date", default="2026-10-23")
    ap.add_argument("--new", required=True, type=pathlib.Path)
    ap.add_argument("--new-date", required=True)
    ap.add_argument("--out", required=True, type=pathlib.Path)
    ap.add_argument("--printed", type=pathlib.Path)
    a = ap.parse_args(argv)
    return run(a.old, a.old_date, a.new, a.new_date, a.out, a.printed)


if __name__ == "__main__":
    sys.exit(main())
