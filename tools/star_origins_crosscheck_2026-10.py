#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""star_origins_crosscheck_2026-10.py — check the star-origins map against every human-verified
statement of where a star came from that exists on this machine. Repo-authored 2026-09-23; revised the
same day with the map revision (human origins now drive the map). Read-only; no network.

Two checks:
  A. The override table data/paper_inputs/star_origins_2026-10/human_origin_overrides.csv against the
     records it was read from: every event with a record has a row and no row lacks a record; each
     row's country is the record's country wherever the record states one (V, P); and the snapshot
     name of the institution a row names appears in the record's text (a distinctive word shared, see
     same_institution); a row whose record files the star under an alias id names that id in
     source_docs, and no other row names one. Any failure is printed and the script exits 1.
  B. The OpenAlex rule (the machine_* columns of output/paper/star_origins_2026-10.csv, written by
     analysis/paper/fig_star_origins.py) against the human origins: per event, against the override
     row (country, institution id); per record, against the record's own text (as in the first
     version of this check).

Human records (all written by people checking CVs, ORCID, official pages — never OpenAlex):
  V  a restricted record of 2026-07-20 (the 57-candidate economics event check, not shipped), table §2
     (16 economics events, its origin (country) column = origin institution + country code); matched to events by
     name -> star id (legacy star_check_coverage_2026-09-14.csv) and school.
  P  the poach-gate verdicts (legacy multidisc_gold_2026-08-10/data/
     poach_fn_verdicts_{econ,chemistry,math_stats}_2026-08-15.csv), rows of ANY verdict (the verdict
     judges the poach gate, not the record of the star's post; since 2026-09-23 a human check is used wherever one exists):
     column origin_country_pre (country, often with the institution in brackets) and column reason
     (the career text, used for the institution check A). A row is matched to an event by the star's
     id, or, when the file lists the star under another OpenAlex id (an alias), by the same folded
     name (legacy star_check_coverage_2026-09-14.csv), the same field and the same arrival year
     (arrival_true = the event's arrival year), which must single out one event (alias_event). At
     cal2026-10 the rows matched by id are all INCLUDE / UNCERTAIN; one chemistry row is matched by
     alias (verdict REJECT_local); the override row names the alias in source_docs
     ("#author_id=<alias>"), which check A requires.
  U  the U4-flagged recheck (legacy multidisc_gold_2026-08-10/data/
     poach_fn_recheck_econ_U4flagged9_2026-08-16.csv), verdict confirmed: column prior_au_detail. These
     are the 5 economics events whose arrival_source in data/raw_verified/events_econ_cal2026-08-28.csv
     is human_web_verified_round2 but which are not in the verdict file (the first version missed them).
  R  the 2026-09-22 recheck identity anchors (data/star_recheck_2026-09-22/adjudication/*.json, not shipped): each
     star's career, read by two adjudicators. A word match against an anchor says only that the
     institution appears somewhere in the career, not that it was the post before arrival; the
     pre-arrival post was read by hand into the override table.
Country parse: V/P country codes or names before the first bracket, plus "(XX)" codes. Institution
comparison (same_institution): a distinctive word of the machine or override institution's name
(not "university", "of", ...; common abbreviations such as MIT, UCLA, CNRS, JRC expanded) appears in
the human text; a name made only of generic words must appear whole.

Writes output/paper/star_origins_crosscheck_2026-10.json: counts and per-event flags only — no
personal names and no raw record text (the records name coauthors). Run after fig_star_origins.py:
    setup/.venv/bin/python tools/star_origins_crosscheck_2026-10.py
"""
from __future__ import annotations

import collections
import csv
import json
import pathlib
import re
import sys
import unicodedata

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from analysis.lib.paths import load_paths  # noqa: E402

VAULT_REL = "restricted/econ_event_checks_2026-07-20.md"   # a restricted record (not shipped)
COVERAGE_REL = "star_check_coverage_2026-09-14/star_check_coverage.csv"
VERDICT_REL = "multidisc_gold_2026-08-10/data/poach_fn_verdicts_{f}_2026-08-15.csv"
U4_REL = "multidisc_gold_2026-08-10/data/poach_fn_recheck_econ_U4flagged9_2026-08-16.csv"
OVERRIDES = REPO / "data" / "paper_inputs" / "star_origins_2026-10" / "human_origin_overrides.csv"
INSTITUTIONS = REPO / "data" / "paper_inputs" / "star_origins_2026-10" / "institutions.csv"
FIELDS = ("econ", "chemistry", "math_stats")
NAME_CC = {"united states": "US", "usa": "US", "us": "US", "united kingdom": "GB", "uk": "GB",
           "hong kong": "HK", "italy": "IT", "new zealand": "NZ", "canada": "CA",
           "netherlands": "NL", "france": "FR", "germany": "DE"}
STOP = {"university", "universite", "universitat", "universita", "universidad", "college", "school",
        "institute", "institut", "national", "research", "centre", "center", "department", "of",
        "the", "and", "for", "de", "des", "du", "la", "le", "di", "technology", "sciences", "science",
        "economics", "studies", "state", "royal", "faculty", "business", "london", "paris", "office",
        "health", "postdoc", "professor", "lecturer", "fellow", "senior", "assoc", "asst", "before",
        "earlier", "that", "then", "phd", "dphil", "prof", "from", "with", "visiting", "univ",
        "united", "states"}
#: abbreviations the human texts use, expanded before the word comparison
ALIASES = {"MIT": "Massachusetts", "UCLA": "California Los Angeles", "LSE": "London School Political",
           "UCL": "University College London", "NYU": "New York", "UCSD": "California San Diego",
           "UNC": "North Carolina", "UBC": "British Columbia", "ETH": "Eidgenossische",
           "CNRS": "Centre National Recherche Scientifique", "Sciences Po": "Etudes Politiques",
           "INRA": "Institut National Recherche Agronomique", "TSE": "Toulouse", "FU Berlin": "Freie Berlin",
           "JRC": "Joint Research", "Cal Poly": "California Polytechnic", "HKUST": "Hong Kong Science",
           "NTU": "Nanyang Technological", "IITP": "Information Transmission Problems", "Padova": "Padua"}


def shown(p: pathlib.Path) -> str:
    """A path for printing: relative to the repo when it lies inside it, else absolute (the output
    directory can sit outside the repo under $SAR_PATHS_CONFIG)."""
    try:
        return str(p.resolve().relative_to(REPO))
    except ValueError:
        return str(p)


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def expand(s: str) -> str:
    """The text with each abbreviation followed by its expansion."""
    for a, full in ALIASES.items():
        s = re.sub(r"\b%s\b" % re.escape(a), a + " " + full, s)
    return s


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", fold(expand(s))) if w not in STOP}


def same_institution(name: str, human: str) -> bool:
    """A distinctive word shared; when the name has none (all generic), the folded full name must
    appear in the (abbreviation-expanded) human text."""
    mw = words(name)
    if mw:
        return bool(mw & words(human))
    return re.sub(r"[^a-z]+", " ", fold(name)).strip() in re.sub(r"[^a-z]+", " ", fold(expand(human)))


def first_clause(text: str) -> str:
    """The origin a verdict names first: inside the first brackets, up to the first ';'."""
    m = re.search(r"[(（]([^)）]*)", text)
    return (m.group(1) if m else text).split(";")[0]


def countries(s: str) -> list[str]:
    head = re.split(r"[(（]", s)[0]
    out = []
    for part in re.split(r"[/;,]", head):
        p = part.strip().lower()
        if not p:
            continue
        if p in NAME_CC:
            out.append(NAME_CC[p])
        elif re.fullmatch(r"[a-z]{2}", p):
            out.append(p.upper())
    out += re.findall(r"\(([A-Z]{2})\)", s)          # vault style: "... (US)"
    return sorted(set(out))


def star_of_rows() -> dict[tuple[str, int], str]:
    out = {}
    for f in FIELDS:
        with open(REPO / "data" / "cal2026-10" / f"events_{f}_cal2026-10.csv", newline="", encoding="utf-8") as fh:
            for k, r in enumerate(csv.DictReader(fh), 1):
                out[(f, k)] = r["star_id"] if f == "econ" else r["author_id"]
    return out


def arrival_years() -> dict[tuple[str, str], int]:
    """(field, star id) -> arrival year, from the cal2026-10 event tables."""
    out = {}
    for f in FIELDS:
        with open(REPO / "data" / "cal2026-10" / f"events_{f}_cal2026-10.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                sid = r["star_id"] if f == "econ" else r["author_id"]
                out[(f, sid)] = int(r["arrival_year"] if f == "econ" else r["arrival_corrected"])
    return out


def alias_event(field: str, name: str, arrival: str, names: dict, arrivals: dict,
                events: set[tuple[str, str]]) -> tuple[str, str] | None:
    """The one event of `field` whose star has this folded name and this arrival year (a record that
    files the star under another OpenAlex id); None when no event or more than one qualifies."""
    nm = fold(name).split()
    try:
        yr = int(arrival)
    except ValueError:
        return None
    hits = [(field, sid) for sid, parts, _sc in names[field]
            if parts == nm and (field, sid) in events and arrivals.get((field, sid)) == yr]
    return hits[0] if len(hits) == 1 else None


def load_human(legacy_v2: pathlib.Path, legacy_thesis: pathlib.Path, events: set[tuple[str, str]]) -> tuple[dict, dict]:
    """(field, star id) -> list of records {source, countries, has_institution, institution_text,
    full_text, alias}; only events in `events`. `alias` is the OpenAlex id a record files the star
    under when that is not the event's star id (P rows matched by alias_event), else "". Also returns
    bookkeeping (vault rows, unmatched, verdicts of the matched P rows, P rows matched by alias)."""
    human: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    names = collections.defaultdict(list)
    with open(legacy_v2 / COVERAGE_REL, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            names[r["discipline"]].append((r["star_id"], fold(r["name"]).split(), r["school"]))
    arrivals = arrival_years()
    p_verdicts: collections.Counter = collections.Counter()
    by_alias = []
    for f in FIELDS:
        with open(legacy_v2 / VERDICT_REL.format(f=f), newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                key, alias = (f, r["author_id"]), ""
                if key not in events:
                    key = alias_event(f, r["name"], r["arrival_true"], names, arrivals, events)
                    if key is None:
                        continue
                    alias = r["author_id"]
                    by_alias.append([f, key[1], alias, r["verdict"]])
                p_verdicts[r["verdict"]] += 1
                t = r["origin_country_pre"]
                human[key].append({
                    "source": "P_poach_verdict", "countries": countries(t), "has_institution": "(" in t,
                    "institution_text": first_clause(t), "full_text": t + " " + r["reason"], "alias": alias})
    with open(legacy_v2 / U4_REL, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["verdict"] == "confirmed" and ("econ", r["author_id"]) in events:
                human[("econ", r["author_id"])].append({
                    "source": "U_u4flagged_recheck", "countries": [], "has_institution": False,
                    "institution_text": "", "full_text": r["prior_au_detail"], "alias": ""})
    sec = (legacy_thesis / VAULT_REL).read_text(encoding="utf-8").split("## 2.")[1].split("**证据链接")[0]
    unmatched, n_vault = [], 0
    for line in sec.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*([^|]+?)\s*\|\s*(\d{4})\s*\|\s*[^|]*?\s*\|\s*([^|]+?)\s*\|", line)
        if not m:
            continue
        n_vault += 1
        num, school, name, _yr, orig = m.groups()
        nm = fold(name).split()
        hits = [sid for sid, parts, sc in names["econ"] if sc == school.lower()
                and parts[-1] == nm[-1] and parts[0][:1] == nm[0][:1] and ("econ", sid) in events]
        if len(hits) != 1:
            unmatched.append({"row": int(num), "school": school, "hits": len(hits)})
            continue
        human[("econ", hits[0])].append({
            "source": "V_vault_2026-07-20", "row": int(num), "countries": countries(orig),
            "has_institution": True, "institution_text": re.sub(r"[（(].*$", "", orig).strip(), "full_text": orig,
            "alias": ""})
    # the 2026-09-22 recheck anchors (data/star_recheck_2026-09-22/, not shipped)
    for p in sorted((REPO / "data" / "star_recheck_2026-09-22" / "adjudication").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if (d["field"], d["author_id"]) in events:
            human[(d["field"], d["author_id"])].append({
                "source": "R_recheck_anchor", "countries": [], "has_institution": False,
                "institution_text": "", "full_text": d.get("identity_anchor") or "", "alias": ""})
    return human, {"vault_rows": n_vault, "vault_rows_unmatched": unmatched,
                   "poach_verdict_rows_by_verdict": dict(sorted(p_verdicts.items())),
                   "poach_verdict_rows_by_alias": by_alias}


def check_overrides(overrides: list[dict], human: dict, inst: dict) -> dict:
    """Check A. Returns the problems (all lists empty = pass) and counts."""
    ov_keys = {(r["discipline"], r["star_id"]) for r in overrides}
    problems = {"missing_override": sorted(set(human) - ov_keys), "override_without_record": sorted(ov_keys - set(human)),
                "country_mismatch": [], "institution_not_in_record": [], "source_docs_mismatch": [],
                "alias_mismatch": []}
    # source -> the marker its source_docs entry carries (the records are restricted, not shipped)
    code = {"P_poach_verdict": "poach_fn_verdicts_", "U_u4flagged_recheck": "U4flagged9",
            "V_vault_2026-07-20": "57候选逐人查证", "R_recheck_anchor": "star_recheck_2026-09-22"}
    for r in overrides:
        key = (r["discipline"], r["star_id"])
        recs = human.get(key, [])
        for h in recs:
            if h["countries"] and r["country_code"] not in h["countries"]:
                problems["country_mismatch"].append([*key, h["source"], r["country_code"], h["countries"]])
        listed = {src for src, marker in code.items() if marker in r["source_docs"]}
        if listed != {h["source"] for h in recs}:
            problems["source_docs_mismatch"].append([*key, sorted(listed), sorted({h["source"] for h in recs})])
        # a record found under an alias id must name that id in source_docs, and only then
        named = sorted(re.findall(r"#author_id=(A\d+)", r["source_docs"]))
        if named != sorted(h["alias"] for h in recs if h.get("alias")):
            problems["alias_mismatch"].append([*key, named, sorted(h["alias"] for h in recs if h.get("alias"))])
        if r["placement"] == "human_institution" and recs:
            name = inst[r["institution_id"]]["display_name"]
            if not same_institution(name, " ".join(h["full_text"] for h in recs)):
                problems["institution_not_in_record"].append([*key, r["institution_id"], name])
    return problems


def main() -> None:
    P = load_paths()
    legacy_v2, legacy_thesis = pathlib.Path(P["legacy_v2_output"]), pathlib.Path(P["legacy_thesis"])
    star_of = star_of_rows()
    machine = list(csv.DictReader(open(P["output"] / "paper" / "star_origins_2026-10.csv", newline="", encoding="utf-8")))
    by_star = {(r["discipline"], star_of[(r["discipline"], int(r["event_row"]))]): r for r in machine}
    human, book = load_human(legacy_v2, legacy_thesis, set(by_star))
    overrides = list(csv.DictReader(open(OVERRIDES, newline="", encoding="utf-8")))
    inst = {r["institution_id"]: r for r in csv.DictReader(open(INSTITUTIONS, newline="", encoding="utf-8"))}

    # ---- A: the override table against the records
    problems = check_overrides(overrides, human, inst)
    # ---- B1: the OpenAlex rule against the human origin of each event (override row, as drawn)
    per_event = []
    for key in sorted(human):
        m = by_star[key]
        per_event.append({"discipline": key[0], "event_row": int(m["event_row"]), "school": m["school"],
                          "sources": sorted(h["source"] for h in human[key]),
                          "placement": m["origin_placement"], "human_country": m["origin_country"],
                          "machine_country": m["machine_country"],
                          "country_agrees": m["machine_country"] == m["origin_country"],
                          "institution_agrees": m["machine_institution_id"] == m["origin_institution_id"],
                          "human_institution": m["origin_institution"], "machine_institution": m["machine_institution"]})
    by_disc = collections.defaultdict(lambda: [0, 0, 0])
    for r in per_event:
        by_disc[r["discipline"]][0] += 1
        by_disc[r["discipline"]][1] += r["country_agrees"]
        by_disc[r["discipline"]][2] += r["institution_agrees"]
    # ---- B2: the OpenAlex rule against each record's own text (first-version comparison, extended)
    rows = []
    for key, hs in sorted(human.items()):
        m = by_star[key]
        for h in hs:
            ctry = "no_country_stated" if not h["countries"] else (
                "agree" if m["machine_country"] in h["countries"] else "DISAGREE")
            if h["has_institution"]:
                inst_cmp = "agree" if same_institution(m["machine_institution"], h["institution_text"]) else "differ"
            else:   # U / R: whole career text; a word match is not a pre-arrival check
                inst_cmp = "mentioned" if same_institution(m["machine_institution"], h["full_text"]) else "not_mentioned"
            rows.append({"discipline": key[0], "event_row": int(m["event_row"]), "source": h["source"],
                         "human_countries": h["countries"], "machine_country": m["machine_country"],
                         "machine_rule": m["machine_rule"], "machine_year_gap": int(m["machine_year_gap"]),
                         "country": ctry, "institution": inst_cmp})
    with open(REPO / "data" / "raw_verified" / "events_econ_cal2026-08-28.csv", newline="", encoding="utf-8") as fh:
        ledger = {r["star_id"]: r for r in csv.DictReader(fh)}
    web = {s for s, r in ledger.items() if r["arrival_source"].startswith("human_web_verified") and ("econ", s) in by_star}
    summary = {
        "events_with_any_human_record": len(human),
        "events_by_discipline": dict(sorted(collections.Counter(d for d, _ in human).items())),
        "events_by_source": dict(sorted(collections.Counter(h["source"] for hs in human.values() for h in hs).items())),
        "events_only_in_recheck_anchor": sum(1 for hs in human.values() if {h["source"] for h in hs} == {"R_recheck_anchor"}),
        "override_rows": len(overrides),
        "override_check_problems": {k: len(v) for k, v in problems.items()},
        "machine_vs_human_by_event": {d: {"events": n, "country_agrees": c, "institution_agrees": i}
                                      for d, (n, c, i) in sorted(by_disc.items())},
        "machine_vs_human_by_event_pooled": {"events": len(per_event),
                                             "country_agrees": sum(r["country_agrees"] for r in per_event),
                                             "institution_agrees": sum(r["institution_agrees"] for r in per_event)},
        "machine_vs_record_text": {"comparisons": len(rows),
                                   "country": dict(sorted(collections.Counter(r["country"] for r in rows).items())),
                                   "institution": dict(sorted(collections.Counter(r["institution"] for r in rows).items()))},
        "vault_rows": book["vault_rows"], "vault_rows_unmatched": book["vault_rows_unmatched"],
        "poach_verdict_rows_by_verdict": book["poach_verdict_rows_by_verdict"],
        "poach_verdict_rows_by_alias": len(book["poach_verdict_rows_by_alias"]),
        "econ_ledger_human_web_rows_in_cal": len(web),
        "econ_ledger_human_web_rows_with_a_record": sum(("econ", s) in human for s in web),
    }
    report = {"_about": "tools/star_origins_crosscheck_2026-10.py (no personal names, no record text)",
              "summary": summary, "override_check_problems": problems,
              "poach_verdict_rows_by_alias": [dict(zip(("discipline", "star_id", "alias_id", "verdict"), a))
                                              for a in book["poach_verdict_rows_by_alias"]],
              "machine_vs_human_disagreements": [r for r in per_event if not r["country_agrees"] or not r["institution_agrees"]],
              "machine_vs_human_by_event": per_event, "machine_vs_record_text": rows}
    dest = P["output"] / "paper" / "star_origins_crosscheck_2026-10.json"
    dest.write_text(json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1, sort_keys=True, ensure_ascii=False))
    print(f"-> {shown(dest)}")
    if any(problems.values()):
        print("OVERRIDE CHECK FAILED:", json.dumps(problems, ensure_ascii=False))
        raise SystemExit(1)
    print("OVERRIDE_CHECK_OK")


if __name__ == "__main__":
    main()
