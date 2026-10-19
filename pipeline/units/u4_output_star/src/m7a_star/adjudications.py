"""m7a consumption of manual adjudications: person-by-person arrival-year checks of 15 stars + the "part-time before full-time arrival" definition (fail-loud).

In plain words: the star-determination path must consume two rounds of manual adjudications:
  Round 1, changes follow the evidence:
  (1) A5018638208 adjunct_q3 -> removed from the candidate pool (rule: "honorary/visiting/adjunct labels do not count as employed" and
     the rule "pure foreign poach = moved in from abroad": neither is satisfied, so this is not a star-parachute event);
  (2) A5086095616 prior_au_employment=True (a local transfer, with an evidence page) -> is_foreign_poach forced False (rule: "never employed in Australia before";
     the star flag is computed as usual, the person is only removed from the "pure foreign poach" treated group).
  Round 2, new definition: "part-time or honorary affiliations before full-time arrival, and
  mis-attributed signatures, do not count as 'having worked in Australia'". It is executed in two sections:
  (3) signal_discards: discard contaminated / part-time-period attribution signals one by one (author x institution x year window,
     each with evidence + URL) -> _foreign_poach_flags does not use these rows when judging "previously in Australia", so poach is judged back to True
     **organically** on the remaining clean evidence (A5006190609 mis-attribution / A5059428122, A5059554264 part-time periods).
  (4) arrival_verifications (manually confirmed years): stars whose roster row has no human_verified
     (types A5062087249/A5001034699/A5072079903) have their arrival year confirmed by hand against the evidence table -> registered in the adjudication file,
     for the supplementary rule "manual confirmation prevails" of the events consistency gate to recognise (year must == the frozen arrival year).

Ban on poach=True (still in force after round 2): poach_dispositions may **only force False**: forcing
True without grounds still raises ValueError. The **only legitimate path** to restore True = indirect discard via signal_discards with
a manual authorisation statement + the URL of every piece of evidence (so is_foreign_poach judges itself back to True on the remaining evidence), never a hard-coded flag value.

Adjudication file = u0p5_roster/roster_fix_2026-07-10c_star_arrival_annotations.json under the derived root
(v2, contains all of v1 plus the two round-2 sections; the earlier v1 file
is kept unchanged and not overwritten; the roster-side u0p5 roster.star_arrival_fix still consumes v1).
Consumption discipline: reading is fail-loud (missing file / missing authorisation statement / discard entry missing evidence or the URL key -> ValueError,
never skipped silently). verify_roster_matches_fixes = a safety gate: the roster version U4 reads must really carry the corrected years,
guarding against silent drift of "adjudication changed but pointing at the old roster". Pure function + read-only JSON, no writes.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

# Location of the adjudication file (relative to derived_root; this is v2, v1 is kept unchanged and not overwritten).
ADJUDICATIONS_SUB = "u0p5_roster/roster_fix_2026-07-10c_star_arrival_annotations.json"


def _parse_signal_discards(ann: dict) -> dict[str, list[dict]]:
    """signal_discards section -> {aid: [entries]} (each: institution + year window + evidence + URL, an auditable adjudication).

    Entry validation (fail-loud; an entry missing evidence raises): institution_id non-empty / year_from<=year_to both int /
    evidence non-empty / the "url" key must be present (may be null, but a missing key means the "URL for every piece of evidence" form was not followed: rejected).
    """
    discards: dict[str, list[dict]] = {}
    for aid, entries in ann.get("signal_discards", {}).items():
        if not entries:
            raise ValueError(
                f"load_star_adjudications: signal_discards {aid} has an empty entry list — "
                "an empty discard adjudication is meaningless; fail-loud")
        parsed = []
        for i, e in enumerate(entries):
            inst = e.get("institution_id")
            y0, y1 = e.get("year_from"), e.get("year_to")
            ok_years = isinstance(y0, int) and isinstance(y1, int) and y0 <= y1
            if not inst or not ok_years or not e.get("evidence") or "url" not in e:
                raise ValueError(
                    f"load_star_adjudications: signal_discards {aid}[{i}] entry is malformed "
                    f"(institution_id={inst!r}, year_from={y0!r}, year_to={y1!r}, "
                    f"evidence={'yes' if e.get('evidence') else 'missing'}, "
                    f"url key={'present' if 'url' in e else 'missing'}) — an auditable adjudication needs institution + year window + "
                    "evidence + URL key; fail-loud")
            parsed.append({
                "dept_key": e.get("dept_key"), "institution_id": inst,
                "year_from": int(y0), "year_to": int(y1),
                "reason": str(e.get("reason") or ""),
                "evidence": e["evidence"], "url": e.get("url"),
            })
        discards[aid] = parsed
    return discards


def _parse_arrival_verifications(ann: dict) -> dict[str, dict]:
    """arrival_verifications section -> {aid: {year, source_kind, evidence, url, dept_key}}.

    year must be int, evidence non-empty, the "url" key present (may be null), the same form as signal_discards.
    """
    verifs: dict[str, dict] = {}
    for aid, v in ann.get("arrival_verifications", {}).items():
        if not isinstance(v.get("year"), int) or not v.get("evidence") or "url" not in v:
            raise ValueError(
                f"load_star_adjudications: arrival_verifications {aid} is malformed "
                f"(year={v.get('year')!r}, evidence={'yes' if v.get('evidence') else 'missing'}, "
                f"url key={'present' if 'url' in v else 'missing'}) — fail-loud")
        verifs[aid] = {
            "dept_key": v.get("dept_key"), "year": int(v["year"]),
            "source_kind": str(v.get("source_kind") or ""),
            "evidence": v["evidence"], "url": v.get("url"),
        }
    return verifs


def _parse_work_pollution_discards(ann: dict) -> dict[str, list[dict]]:
    """work_pollution_discards section -> {aid: [{work_id, reason, evidence, url}]}.

    Case of A5071656006 (a 1985 meteorology paper = namesake contamination): exclude by work_id exactly
    a single mis-merged paper of an author (cures first_pub/stock contamination), for cases robust_first_pub cannot drop
    (this paper 1985 -> true career 1995, gap exactly = max_leading_gap = 10, so it is not dropped). Auditable, in the same
    form as signal_discards: each entry has non-empty work_id / non-empty evidence / the "url" key present (may be null);
    the entry list is non-empty. Any violation -> ValueError fail-loud (a mistyped id or an empty adjudication is never silent).
    """
    discards: dict[str, list[dict]] = {}
    for aid, entries in ann.get("work_pollution_discards", {}).items():
        if not entries:
            raise ValueError(
                f"load_star_adjudications: work_pollution_discards {aid} has an empty entry list — "
                "an empty discard adjudication is meaningless; fail-loud")
        parsed = []
        for i, e in enumerate(entries):
            wid = e.get("work_id")
            if not wid or not e.get("evidence") or "url" not in e:
                raise ValueError(
                    f"load_star_adjudications: work_pollution_discards {aid}[{i}] entry is malformed "
                    f"(work_id={wid!r}, evidence={'yes' if e.get('evidence') else 'missing'}, "
                    f"url key={'present' if 'url' in e else 'missing'}) — an auditable adjudication needs work_id + "
                    "evidence + URL key; fail-loud")
            parsed.append({
                "work_id": str(wid), "reason": str(e.get("reason") or ""),
                "evidence": e["evidence"], "url": e.get("url"),
            })
        discards[aid] = parsed
    return discards


def load_star_adjudications(derived_root, *, sub: str = ADJUDICATIONS_SUB) -> dict:
    """Read the adjudication JSON -> six consumption maps (fail-loud).

    Returns {"exclude_candidates": {aid: reason}, "poach_overrides": {aid: False},
          "year_fixes": {aid: {dept_key, year_start}},
          "signal_discards": {aid: [entries]}, "arrival_verifications": {aid: {...}},
          "work_pollution_discards": {aid: [{work_id, ...}]},
          "authorized_by": str, "path": str, "sha256": str}.
    - Missing file / missing authorized_by -> ValueError (an unauthorised adjudication is never consumed);
    - of identity_dispositions only entries with exclude_from_candidates=True enter the exclusion map;
    - is_foreign_poach in poach_dispositions must be False (it may only remove a person from the treated group) --
      a True raises. This ban is not relaxed by the round-2 definition: the only legitimate path to restore True = indirect discard
      via signal_discards (judged back organically), see the module docstring;
    - entry form validation for signal_discards / arrival_verifications is in each _parse (missing evidence / URL key raises).
    """
    p = Path(derived_root) / sub
    if not p.is_file():
        raise ValueError(
            f"load_star_adjudications: adjudication file not found at {p} — the star-classification production path must consume "
            "the manual-review adjudications (roster_fix_2026-07-10c_star_arrival_annotations.json), "
            "fail-loud, never silently skip"
        )
    raw = p.read_bytes()
    ann = json.loads(raw.decode("utf-8"))
    if not ann.get("authorized_by"):
        raise ValueError(
            f"load_star_adjudications: {p} lacks authorized_by — an adjudication without an authorization statement is not consumed")

    exclude: dict[str, str] = {}
    for aid, d in ann.get("identity_dispositions", {}).items():
        if d.get("exclude_from_candidates") is True:
            exclude[aid] = str(d.get("note") or d.get("disposition"))

    poach: dict[str, bool] = {}
    for aid, d in ann.get("poach_dispositions", {}).items():
        v = d.get("is_foreign_poach")
        if v is not False:
            raise ValueError(
                f"load_star_adjudications: poach adjudication {aid} has is_foreign_poach={v!r} — "
                "a manual-review adjudication may only force False (removing the case from the treated group); the only legitimate way to restore True = "
                "an indirect discard in signal_discards with evidence + URL (judged back to organic), never a hard override"
            )
        poach[aid] = False

    fixes = {aid: {"dept_key": fx["dept_key"], "year_start": int(fx["year_start"])}
             for aid, fx in ann.get("year_start_fixes", {}).items()}

    return {"exclude_candidates": exclude, "poach_overrides": poach,
            "year_fixes": fixes,
            "signal_discards": _parse_signal_discards(ann),
            "arrival_verifications": _parse_arrival_verifications(ann),
            "work_pollution_discards": _parse_work_pollution_discards(ann),
            "authorized_by": ann["authorized_by"],
            "path": str(p), "sha256": hashlib.sha256(raw).hexdigest()}


def verify_roster_matches_fixes(roster_rows: Iterable[dict],
                                year_fixes: Mapping[str, dict]) -> None:
    """Safety gate: every year correction must already be in the roster rows (year_start == corrected year and human_verified).

    If U4 points at an old (uncorrected) roster version -> ValueError naming it, blocking at once; this guards against silent definition drift of the kind
    "the adjudication changed but the roster read was not replaced" (the point of the correction is the roster numbers themselves).
    """
    by_key = {(r["author_id"], r["dept_key"]): r for r in roster_rows
              if r.get("author_id") is not None}
    bad = []
    for aid, fx in sorted(year_fixes.items()):
        r = by_key.get((aid, fx["dept_key"]))
        if r is None:
            bad.append(f"{aid}: 名册无该行 ({fx['dept_key']})")
        elif r.get("year_start") != fx["year_start"] or r.get("human_verified") is not True:
            bad.append(
                f"{aid}: 名册 year_start={r.get('year_start')} hv={r.get('human_verified')}"
                f" ≠ 裁定 {fx['year_start']} (hv=True)")
    if bad:
        raise ValueError(
            "verify_roster_matches_fixes: the roster U4 read does not carry the roster fixes — "
            "wrong version pointed at or fixes not written to disk; fail-loud: " + "; ".join(bad)
        )


def human_verified_arrival_basis(roster_rows: Iterable[dict],
                                 arrival_verifications: Mapping[str, dict],
                                 star_rows: Iterable[dict]) -> dict[str, str]:
    """The hv criterion of the supplementary rule of the events consistency gate: is each star's arrival year confirmed by hand?

    Returns {author_id: basis string}, giving a basis **only when** the frozen arrival year (star_rows[i]["arrival"]) is **equal** to the manually confirmed
    year (a year mismatch = a three-way disagreement, which does not count as "manual confirmation prevails" and stays HALT):
      - roster row human_verified=True and year_start == arrival ->
        "roster:human_verified_web" (evidence starts with human_verified_web) or
        "roster:human_verified" (manual / raw_affil_year etc., manually verified roster);
      - adjudication arrival_verifications[aid].year == arrival ->
        "adjudication:arrival_verification(<source_kind>)" (manually confirmed years,
        types A5062087249/A5001034699/A5072079903 whose roster rows carry no hv).
    If both exist -> roster first (web before manual). No manual confirmation -> absent from the map (HALT discipline).
    """
    hv_rows: dict[str, list] = {}
    for r in roster_rows:
        aid = r.get("author_id")
        if aid and r.get("human_verified") is True and r.get("year_start") is not None:
            hv_rows.setdefault(aid, []).append(r)

    basis: dict[str, str] = {}
    for s in star_rows:
        aid, arr = s["author_id"], s.get("arrival")
        if arr is None:
            continue
        matched = [r for r in hv_rows.get(aid, ()) if r["year_start"] == arr]
        if matched:
            web = any(str(r.get("evidence") or "").startswith("human_verified_web")
                      for r in matched)
            basis[aid] = "roster:human_verified_web" if web else "roster:human_verified"
            continue
        v = arrival_verifications.get(aid)
        if v and v["year"] == arr:
            basis[aid] = (f"adjudication:arrival_verification"
                          f"({v['source_kind'] or 'human'})")
    return basis
