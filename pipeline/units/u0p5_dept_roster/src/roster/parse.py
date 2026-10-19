"""U0.5 (1) parsing - raw Chrome-crawled archive of Monash Pure Profiles -> structured records.

What it does:
  Parses the archived Monash economics faculty pages grabbed by the browser (one person per line,
  segments separated by the pipe `|`) into structured dicts, for the downstream author_id alignment + Table B.

Source format (real archive monash_econ_pure_raw_2026-06-29.txt, one person per line):
    <display_name> | <title_raw> | <years or (no years)> [| <Impact Labs or flag:* or ★note>]*
  Examples:
    Alex Example | Lecturer | 2023-2025
    Sam Example | Named Chair | 2002-2026 | Impact Labs
    Robin Example | ADJUNCT PROFESSOR | 2007-2023 | flag:adjunct
    Kim Example | Research Fellow | (no years)
    Yves Zenou | VCDP & named Chair BusEco | 1995-2026 | ★GOLDEN star candidate, ...

Non-person lines (never enter the list): comment lines starting with `#`, `=== PAGE ... ===` page headers,
statistics footnotes.

Output per record (this unit's intermediate form, not Table B):
  {display_name, email, title_raw, year_start, year_end, is_adjunct, is_emeritus, center}
  - email: the real archive has no email -> all None (the column is kept so the field set stays aligned;
    the pages of other schools may have it).
  - year_start/year_end: "YYYY-YYYY" -> (int, int); "(no years)" / missing -> (None, None).
  - is_adjunct/is_emeritus: recognizes the flag:adjunct / flag:emeritus tag or the title text
    (ADJUNCT / Emeritus); either one is enough for True (the archive gives both the flag and the title text).
  - center: matches "Impact Labs" -> "Impact Labs"; otherwise None.

Hard rule: whether a flag counts as "employed" is a human decision; the parsing layer only **copies + marks**
  and never includes/excludes anybody on the spot. Pure string parsing, zero network, zero IO (the caller reads
  the file and passes the text).
"""
from __future__ import annotations

import re
from typing import Optional

# Year range such as 1995-2026 / 2023-2025 / 2022-2022.
_YEAR_RANGE_RE = re.compile(r"^\s*(\d{4})\s*-\s*(\d{4})\s*$")

# Prefixes/markers of non-person lines (never parsed as a person).
_COMMENT_PREFIX = "#"
_PAGE_MARKER = "==="           # === PAGE ... === / === statistics ===

# center keywords (currently only Impact Labs; an extension point).
_KNOWN_CENTERS = ("Impact Labs",)


def _parse_year_pair(token: str) -> tuple[Optional[int], Optional[int]]:
    """Single token -> (year_start, year_end).

    - "1995-2026" -> (1995, 2026);
    - "(no years)" / not a year range -> (None, None) (no crash, no placeholder number).
    """
    m = _YEAR_RANGE_RE.match(token)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _is_person_line(line: str) -> bool:
    """Is this line a person (excluding comment/page/statistics/blank lines)."""
    s = line.strip()
    if not s:
        return False
    if s.startswith(_COMMENT_PREFIX):
        return False
    if _PAGE_MARKER in s:
        return False
    # A person line contains at least one pipe (name | title | ...).
    return "|" in s


def parse_one(line: str) -> dict:
    """Single person line -> structured record (8 fields).

    Segmentation: split on `|`. Segment 1 = display_name, segment 2 = title_raw,
    the remaining segments are classified one by one (year range / Impact Labs / flag:* / ★note; others are ignored).
    """
    parts = [p.strip() for p in line.split("|")]
    display_name = parts[0].strip()
    title_raw = parts[1].strip() if len(parts) > 1 else ""

    year_start: Optional[int] = None
    year_end: Optional[int] = None
    center: Optional[str] = None

    for tok in parts[2:]:
        t = tok.strip()
        if not t:
            continue
        # 1) year range
        ys, ye = _parse_year_pair(t)
        if ys is not None:
            year_start, year_end = ys, ye
            continue
        # 2) center (Impact Labs)
        matched_center = next((c for c in _KNOWN_CENTERS if c.lower() in t.lower()), None)
        if matched_center is not None:
            center = matched_center
            continue
        # 3) flag:* / (no years) / ★note etc. -> not structured fields (flags are decided uniformly below)
        #    "(no years)" already gave None in year parsing, nothing more to do here.

    # Flag decision: flag:adjunct / flag:emeritus tag or title text (either one gives True).
    line_lower = line.lower()
    is_adjunct = ("flag:adjunct" in line_lower) or ("adjunct" in title_raw.lower())
    is_emeritus = ("flag:emeritus" in line_lower) or ("emeritus" in title_raw.lower())

    return {
        "display_name": display_name,
        "email": None,                 # The Pure archive has no email; the column is kept to align the field set
        "title_raw": title_raw,
        "year_start": year_start,
        "year_end": year_end,
        "is_adjunct": is_adjunct,
        "is_emeritus": is_emeritus,
        "center": center,
    }


def parse_roster_lines(raw_text: str) -> list[dict]:
    """Whole raw archive text -> list of structured records (one per person).

    Comment/page/statistics/blank lines are skipped automatically; the archive order is kept (stable, easier to check by hand).
    """
    out: list[dict] = []
    for line in raw_text.splitlines():
        if not _is_person_line(line):
            continue
        out.append(parse_one(line))
    return out


# ===========================================================================
# UNSW extension - same `|` pipe format, but: no years (year all None) +
#   the flag markers are visiting / emeritus / postdoc (Monash has adjunct / emeritus).
# Reuses _is_person_line / _parse_year_pair / _KNOWN_CENTERS; only the flag decision + field set differ.
# ===========================================================================
def parse_one_unsw(line: str) -> dict:
    """Single UNSW person line -> structured record (UNSW field set).

    Segmentation as for Monash: split on `|`; segment 1 = display_name, segment 2 = title_raw,
    the remaining segments are classified one by one. The UNSW page **gives no years**, so year_start/year_end are in
    practice always None (reuses _parse_year_pair: a non-year token -> (None, None), never filled by guess).

    Flag decision (copy + mark; whether somebody is "employed" is a human decision, the parsing layer does not decide):
      - is_visiting: flag:visiting tag or the title contains "Visiting";
      - is_emeritus: flag:emeritus tag or the title contains "Emeritus" (same criterion as Monash);
      - is_postdoc:  flag:postdoc tag or the title contains "Postdoc"/"Post-Doc"/"Postdoctoral"
                     (UNSW postdoc titles are written in different ways, so the flag tag is the main signal + the title
                     text as a fallback).

    Field set = the Monash 8-field base (display_name/email/title_raw/year_start/year_end/
      is_adjunct/is_emeritus/center) + the UNSW-specific is_visiting/is_postdoc.
      The is_adjunct/center columns are kept to align with the base (this UNSW page has none, always False/None), so
      one schema serves both schools downstream.
    """
    parts = [p.strip() for p in line.split("|")]
    display_name = parts[0].strip()
    title_raw = parts[1].strip() if len(parts) > 1 else ""

    year_start: Optional[int] = None
    year_end: Optional[int] = None
    center: Optional[str] = None

    for tok in parts[2:]:
        t = tok.strip()
        if not t:
            continue
        # 1) year range (this UNSW page has none, but the same parsing path is kept; a non-year -> year untouched)
        ys, ye = _parse_year_pair(t)
        if ys is not None:
            year_start, year_end = ys, ye
            continue
        # 2) center (known centres such as Impact Labs; this UNSW page has none)
        matched_center = next((c for c in _KNOWN_CENTERS if c.lower() in t.lower()), None)
        if matched_center is not None:
            center = matched_center
            continue
        # 3) flag:* / extra title segments (e.g. "Professor") etc. -> not structured fields (flags are decided uniformly below)

    line_lower = line.lower()
    title_lower = title_raw.lower()
    is_visiting = ("flag:visiting" in line_lower) or ("visiting" in title_lower)
    is_emeritus = ("flag:emeritus" in line_lower) or ("emeritus" in title_lower)
    is_postdoc = (
        "flag:postdoc" in line_lower
        or "postdoc" in title_lower            # "Postdoctoral Fellow"
        or "post-doc" in title_lower           # "Post-Doc Fellow"
    )
    # is_adjunct does not occur on this UNSW page (the column is kept to align with the base); still recognized by the Monash criterion (so an adjunct appearing on that page later is not missed).
    is_adjunct = ("flag:adjunct" in line_lower) or ("adjunct" in title_lower)

    return {
        "display_name": display_name,
        "email": None,                 # The UNSW our-people list page has no email; the column is kept to align
        "title_raw": title_raw,
        "year_start": year_start,      # UNSW has no years -> None
        "year_end": year_end,
        "is_visiting": is_visiting,
        "is_emeritus": is_emeritus,
        "is_postdoc": is_postdoc,
        "is_adjunct": is_adjunct,
        "center": center,
    }


def parse_unsw_lines(raw_text: str) -> list[dict]:
    """Whole raw UNSW archive text -> list of structured records (one per person).

    Reuses _is_person_line (comment/separator/blank lines are skipped automatically); the archive order is kept.
    """
    out: list[dict] = []
    for line in raw_text.splitlines():
        if not _is_person_line(line):
            continue
        out.append(parse_one_unsw(line))
    return out
