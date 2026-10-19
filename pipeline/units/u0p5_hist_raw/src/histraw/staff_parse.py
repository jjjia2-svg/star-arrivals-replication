"""Old staff-page name parser — Wayback raw HTML -> structured roster snapshot rows (faithful raw layer).

In plain words: pull out "the people on the list that year" from the stored old pages. Names are kept
exactly as printed on the page (even spelling errors are not corrected; matching names is left to
downstream), the title is stripped into title_raw, navigation noise is kept out; rows are then
aggregated per person into "which years the person appears on the list" ([min,max] + year list, missing
years not filled).

Two real formats:
  - 2006/2007 direct-list type: <a href="/about/staff/example/">Professor Alex Example</a>
  - 2008/2009 slug type: <a href="/eco/staff/sam-example.html">Sam Example</a> (bare name)
  - 2010+ grouped index pages -> names are on sub-pages (prefix two-level crawl, a separate batch).
Three new forms for the UQ pilot (checked on real pages, see test_uq_staff_parse):
  - UQ 2002 type: bare slug `.htm` links + direct-order title and name ("Dr A. Example");
  - UQ 2003-04 type: inverted name "Surname, Title Initials (First)", including a no-comma variant
    ("Example Dr R. (Robin)") -> rebuilt in natural order, with the original printed string stored in
    display_name_printed (faithful and auditable);
  - UQ 2016+ modern type: /profile/<id>/<slug> relative links + direct-order title and name.
"""
from __future__ import annotations

import re

from roster.byline import _write_det

# Person-name link: a slug segment after /staff/ (excluding the /staff/ root, staff-only and the visiting/ directory),
# or a bare relative slug link <slug>.html/.php (2008 type: <surname>-<given>.html with no directory prefix).
# UQ pilot: also bare `.htm` (real UQ 2002-05 pages) and /profile/<id>/<slug> (UQ modern type).
_HREF_RE = re.compile(
    r"(?:/staff/[a-z0-9\-\.'']+(?:/|\.html?)$)|(?:^[a-z0-9\-\.]+\.(?:html?|php)$)"
    r"|(?:/profile/\d+/[a-z0-9\-\.'']+/?$)", re.I)
_TITLE_RE = re.compile(
    r"^(Honorary Associate Professor|Honorary Professor|Honorary Fellow|"
    r"Emeritus Professor|Adjunct Associate Professor|Adjunct Professor|"
    r"Associate Professor|Assistant Professor|A/Prof\.?|"
    r"Professor|Prof\.?|Dr\.?|Mr\.?|Ms\.?|Mrs\.?)\s+(.+)$")  # Match longer prefixes first (review F2)
# Name shape: 2+ capitalised words (abbreviation dots, hyphens and apostrophes allowed).
# UQ pilot: lowercase particles (te/de/van/von...) are allowed between capitalised words — real names
# with lowercase particles (te / de types, currently employed at UQ!) were silently dropped by the old
# shape on real pages; 'and'/'of'/'with' are not particles, so section headings
# (Adjunct and honorary) are still rejected.
_NAME_PARTICLES = r"(?:te|de|van|von|der|den|del|della|da|di|la|le|du|dos|das|do)"
_NAME_RE = re.compile(
    rf"^[A-Z][\w'\-\.]*(\s+(?:{_NAME_PARTICLES}\s+)*[A-Z][\w'\-\.]*)+$")
# Word-count cap (A5 backstop): real names with abbreviation dots run to at most 4 words (e.g. 'C. A. First Last' / 'J. K. C. Last');
# >5 words = several names merged into one string (residue from a missing </a>), rejected outright. This is a parsing-heuristic constant, not an identification choice.
_MAX_NAME_WORDS = 5
_DENY_WORDS = {"staff", "university", "economics", "contact", "intranet", "directory",
               "index", "visiting", "only", "home", "search", "about", "faculty",
               "school", "department", "monash", "unsw", "business", "email", "maps",
               # Group-label words (slipped through on the 2010-12 index pages: Adjunct Academics etc.)
               "academics", "lecturers", "fellows", "professors", "adjunct",
               "sessional", "research", "students", "tutors", "postgraduate",
               "mission", "plan",
               # Review F1: section-heading words (7 of these leaked into the output on real data)
               "information", "links", "fields", "quick", "experiment",
               "materials", "industrial", "organisation", "organization",
               "table", "timetable", "general", "education", "student",
               "principal", "professional",
               # UQ pilot: navigation words on real UQ 2002/2003 pages (Positions Vacant)
               "positions", "vacant"}

# A5: the anchor body never crosses a block-level `<` (so it never swallows the next `<li>`/`<a>`); `</a>` is optional,
# so anchors with a missing closing tag still each become their own row (archived real pages often lack </a>), instead of silently dropping a person or composing a fake name.
# UQ pilot (real 2002/2005 pages): the anchor body allows a WHITELIST of inline format tags
# span/b/i/strong/em (including stray closers — the 2005 template has '<b>Example, Alex</span></b>');
# all other tags are still treated as block boundaries, so the A5 safeguard is unchanged; href quoting in
# all three forms (double / single / none) is accepted (old hand-written HTML).
_LINK_RE = re.compile(
    r'<a\s+[^>]*href\s*=\s*(?:"([^"]+)"|\'([^\']+)\'|([^\s>"\']+))[^>]*>'
    r'((?:[^<]|</?(?:span|b|i|strong|em)[^>]*>)*)(?:</a>)?', re.I)
_TAG_RE = re.compile(r"<[^>]+>")

STAFF_LINE_SCHEMA: dict[str, str] = {
    "dept_key": "str",
    "display_name": "str",
    "title_raw": "str",
    # UQ pilot: when rebuilding an inverted name, keep the page's original printed string (faithful and auditable); direct-order rows always get None.
    "display_name_printed": "str",
    "snapshot_year": "int16",
    "timestamp": "str",
    "href": "str",
    "source_sha": "str",
}


def split_title(text: str) -> tuple[str | None, str]:
    m = _TITLE_RE.match(text)
    if m:
        return m.group(1), m.group(2).strip()
    return None, text


# UQ pilot: inverted name "Surname[,] Title Initials [(First)]" (UQ 2003-04
# academic.htm real page; the comma may be missing — the 'Example Dr R. (Robin)' form).
# Rebuilding to natural order is a STRUCTURAL REORDERING, not a correction: the caller stores the
# original printed string in display_name_printed, so the faithful layer loses nothing.
_INV_TITLE = (r"(?:Assoc\.?\s+Prof\.?|A/Prof\.?|Professor|Prof\.?|Dr\.?|"
              r"Mr\.?|Ms\.?|Mrs\.?|Miss)")
_INV_RE = re.compile(
    rf"^(?P<sur>[A-Z][\w'\-]*),?\s+(?P<title>{_INV_TITLE})\s+"
    rf"(?P<ini>[A-Z](?:\.\s*[A-Z])*\.?)\s*(?:\((?P<first>[A-Za-z][\w'\- ]*)\))?\s*$")
# Comma form without a title (UQ 2006 CMS / 2011-15 accordion real pages: 'Example, Alex') — the comma is
# required (a bare two-word direct-order name must never match here); the surname may have two words
# (Van Der Berg type), and the given-name part has no parentheses.
_INV_PLAIN_RE = re.compile(
    r"^(?P<sur>[A-Z][\w'\-]*(?:\s+[A-Z][\w'\-]*)?),\s+(?P<first>[A-Z][\w'\-\. ]*?)\s*$")


def split_inverted_name(text: str) -> tuple[str | None, str, str] | None:
    """Inverted name -> (title_raw as printed, natural-order name, printed string); a non-inverted form / deny word -> None.

    Two real forms:
      A. With a title: 'Example, Dr A. (Alex)' (the comma may be missing — 'Example Dr R. (Robin)') ->
         with a parenthesised name use "<First> <Surname>"; without one fall back to "<Initials> <Surname>";
      B. No title, plain comma: 'Example, Alex' -> "<First> <Surname>", title=None.
    The title keeps the page's printed form (Prof./Dr, no dots added or removed).
    """
    text = text.strip()
    m = _INV_RE.match(text)
    if m is not None:
        sur, title, ini, first = (m.group("sur"), m.group("title"),
                                  re.sub(r"\s+", "", m.group("ini")), m.group("first"))
        name = f"{first.strip()} {sur}" if first else f"{ini} {sur}"
        if not looks_like_person_name(name):
            return None  # A deny word or a bad shape is never rebuilt into a person name
        return title, name, text
    m = _INV_PLAIN_RE.match(text)
    if m is not None:
        name = f"{m.group('first').strip()} {m.group('sur')}"
        if not looks_like_person_name(name):
            return None
        return None, name, text
    return None


def looks_like_person_name(text: str) -> bool:
    if text.isupper():
        return False  # All caps = section heading (review F1: TIME TABLE GENERAL EDUCATION)
    if not _NAME_RE.match(text):
        return False
    parts = text.split()
    if len(parts) > _MAX_NAME_WORDS:
        return False  # A5 backstop: several names merged into one string (residue from a missing </a>) is never a person name
    words = {w.strip(".").lower() for w in parts}
    return not (words & _DENY_WORDS)


def parse_staff_page(html: str, *, dept_key: str, timestamp: str,
                     source_sha: str = "") -> list[dict]:
    """One old staff page -> list of roster snapshot rows (one row per person, de-duplicated within the page, names verbatim)."""
    year = int(timestamp[:4])
    seen: set[str] = set()
    rows: list[dict] = []
    for m in _LINK_RE.finditer(html):
        href = m.group(1) or m.group(2) or m.group(3)
        raw_text = m.group(4)
        text = _TAG_RE.sub(" ", raw_text)
        text = re.sub(r"\s+", " ", text).strip()
        if not text or not _HREF_RE.search(href.split("?")[0]):
            continue
        title, name = split_title(text)
        printed = None
        if not looks_like_person_name(name):
            # UQ pilot: direct-order name failed -> (1) first try the inverted form (structurally strong, the
            # 'Example Dr R. (Robin)' form); (2) then try stripping a parenthesised nickname
            # ('Robin (Rob) Example' form, the printed string kept as printed). Behaviour on old pages is byte-identical.
            inv = split_inverted_name(text)
            if inv is not None:
                title, name, printed = inv
            else:
                nick = re.sub(r"\s*\([A-Za-z][\w'\-]*\)\s*", " ", name)
                nick = re.sub(r"\s+", " ", nick).strip()
                if nick != name and looks_like_person_name(nick):
                    printed, name = name, nick
                else:
                    continue
        if name in seen:
            continue
        seen.add(name)
        rows.append({"dept_key": dept_key, "display_name": name, "title_raw": title,
                     "display_name_printed": printed,
                     "snapshot_year": year, "timestamp": timestamp,
                     "href": href, "source_sha": source_sha})
    return rows


# UQ pilot: 2011-15 UQ accordion roster type —
#   <h2 class="trigger"><div class="title"><a href="#test">Example, Alex </a></div>
#   <div class="mediacaption">- Professor & Head of School -</div> ...
#   <a href="example-alex">Open this profile in separate window</a>
# The name anchors' href is always '#test' (so link shape cannot filter them) -> split by trigger block,
# take the name from the title div and the title from mediacaption; the profile slug (traceable) goes into href.
# Rows use the same STAFF_LINE_SCHEMA.
_ACC_SPLIT_RE = re.compile(r'<h2\s+class="trigger">', re.I)
_ACC_TITLE_RE = re.compile(r'<div\s+class="title"><a\s[^>]*>([^<]+)</a></div>', re.I)
_ACC_CAPTION_RE = re.compile(r'<div\s+class="mediacaption">\s*-?\s*([^<]*?)\s*-?\s*</div>', re.I)
_ACC_PROFILE_RE = re.compile(r"<a\s+href=\"([a-z0-9\-']+)\"[^>]*>\s*Open this profile", re.I)


def parse_accordion_staff_page(html: str, *, dept_key: str, timestamp: str,
                               source_sha: str = "") -> list[dict]:
    """UQ 2011-15 accordion roster page -> roster snapshot rows (one row per person, de-duplicated within the page, printed string kept)."""
    year = int(timestamp[:4])
    seen: set[str] = set()
    rows: list[dict] = []
    for chunk in _ACC_SPLIT_RE.split(html)[1:]:
        m = _ACC_TITLE_RE.search(chunk)
        if m is None:
            continue
        text = re.sub(r"\s+", " ", m.group(1)).strip()
        title, name = split_title(text)
        printed = None
        if not looks_like_person_name(name):
            inv = split_inverted_name(text)
            if inv is None:
                continue
            title, name, printed = inv
        cap = _ACC_CAPTION_RE.search(chunk)
        if cap and cap.group(1).strip():
            title = cap.group(1).strip()  # In this type the title is always printed in mediacaption
        prof = _ACC_PROFILE_RE.search(chunk)
        href = prof.group(1) if prof else "#accordion"
        if name in seen:
            continue
        seen.add(name)
        rows.append({"dept_key": dept_key, "display_name": name, "title_raw": title,
                     "display_name_printed": printed,
                     "snapshot_year": year, "timestamp": timestamp,
                     "href": href, "source_sha": source_sha})
    return rows


def aggregate_staff_lines(rows: list[dict]) -> list[dict]:
    """Aggregate the years of appearance by (department, name) -> [min,max] + year list + snapshot count. Missing years are not filled (not archived != not on the list)."""
    by: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r["dept_key"], r["display_name"])
        a = by.setdefault(key, {"dept_key": r["dept_key"],
                                "display_name": r["display_name"],
                                "_years": set(), "_titles": set(), "n_snapshots": 0})
        a["_years"].add(int(r["snapshot_year"]))
        if r.get("title_raw"):
            a["_titles"].add(r["title_raw"])
        a["n_snapshots"] += 1
    out = []
    for a in by.values():
        years = sorted(a["_years"])
        out.append({"dept_key": a["dept_key"], "display_name": a["display_name"],
                    "year_start": years[0], "year_end": years[-1],
                    "years_seen": years, "n_snapshots": a["n_snapshots"],
                    "titles_seen": sorted(a["_titles"])})
    return sorted(out, key=lambda r: (r["dept_key"], r["display_name"]))


def write_staff_lines(rows: list[dict], out_dir) -> "pathlib.Path":
    import pathlib

    out_dir = pathlib.Path(out_dir)
    target = out_dir / "wayback_staff_lines.parquet"
    _write_det(rows, dict(STAFF_LINE_SCHEMA), target,
               ("dept_key", "display_name", "timestamp", "href"))
    return target
