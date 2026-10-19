"""Person-page parser — old site's per-person profile page -> (name, title, sub-department hint, arrival hint).

In plain words: each person page prints "this person's full name and title at the time". The name is kept
verbatim, the title goes to title_raw, and a sub-department carried in the title (Department of Economic
History etc.) goes to sub_dept_hint. A year in the biography such as "joined UNSW in 1961" goes only to
the **arrival_hint_year hint column**: the authoritative arrival year is determined by the arrival rules
plus manual review, and this table never overrides it.

Three real formats (659 fetched pages checked):
  - UNSW 2000 type: generic title; the first person-name line in the body = full name, the next line = title;
  - Monash php 2006 type / html 2007 type: <title>/<h1> = (title prefix +) full name, the title word is in the body.
"""
from __future__ import annotations

import re

from histraw.staff_parse import looks_like_person_name, split_title

PERSON_PAGE_SCHEMA: dict[str, str] = {
    "dept_key": "str",
    "display_name": "str",
    "title_raw": "str",
    "sub_dept_hint": "str",
    "arrival_hint_year": "int16",
    "snapshot_year": "int16",
    "timestamp": "str",
    "source_sha": "str",
}

_TITLE_WORDS = re.compile(
    r"\b(Professor|Lecturer|Fellow|Reader|Tutor|Head of|Chair|Dean|Associate|"
    r"Assistant|Emeritus|Visiting|Adjunct|Senior)\b", re.I)
_SUB_DEPT_RE = re.compile(r"((?:Department|School) of [A-Z][A-Za-z ]+?)(?:\s*$|,)")
# Review M1: trust only a year right after our own university's name (a year for another
# university, e.g. 'Indiana University in 1995', is never taken).
# UQ pilot: the institution token is a parameter (_arrival_re); the default (UNSW, Monash) behaves
# as before. Each extended university passes its own token; the M1 safeguard is unchanged (token not
# in the sentence -> no year is ever taken).
_DEFAULT_ARRIVAL_TOKENS: tuple[str, ...] = ("UNSW", "Monash")


def _arrival_re(inst_tokens: tuple[str, ...]) -> re.Pattern:
    alt = "|".join(re.escape(t) for t in inst_tokens)
    return re.compile(
        rf"join(?:ed|ing)\s+(?:the\s+)?(?:{alt})"
        r"[^\d\n]{0,40}\b(19\d\d|20\d\d)\b", re.I)


_ARRIVAL_RE = _arrival_re(_DEFAULT_ARRIVAL_TOKENS)  # Default for the two original universities (backward compatible)


def _text_lines(html: str) -> list[str]:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return [l.strip() for l in text.splitlines() if l.strip()]


def extract_sub_dept(title_line: str | None) -> str | None:
    if not title_line:
        return None
    m = _SUB_DEPT_RE.search(title_line)
    return m.group(1).strip() if m else None


def _slug_tokens(slug: str) -> set[str]:
    return {t for t in re.split(r"[\-\._]+", slug.lower()) if len(t) >= 3}


def parse_person_page(html: str, *, dept_key: str, timestamp: str,
                      source_sha: str = "", url_slug: str | None = None,
                      arrival_inst_tokens: tuple[str, ...] = _DEFAULT_ARRIVAL_TOKENS,
                      ) -> dict | None:
    """One person page -> one record; no name found -> None (the caller counts these; nothing is guessed).

    Review F1 fix: given a url_slug, cross-check it — if the extracted name shares no token with the slug
    (a section heading on a CV/navigation page), return None and never treat it as a person.
    arrival_inst_tokens (UQ pilot): an arrival hint trusts only a year right after one of these
    own-university tokens (M1 safeguard); the default two-university tokens behave as before, and each
    extended university passes its own explicitly."""
    lines = _text_lines(html)

    name = None
    title_raw = None
    for i, line in enumerate(lines[:30]):
        t, candidate = split_title(line)
        if looks_like_person_name(candidate):
            name = candidate
            if t:
                title_raw = t
            # If the name line has no title prefix, check whether the next line is a title
            if title_raw is None and i + 1 < len(lines) and _TITLE_WORDS.search(lines[i + 1]) \
                    and len(lines[i + 1]) < 90:
                title_raw = lines[i + 1]
            break
    if name is None:
        return None
    if url_slug:
        toks = _slug_tokens(url_slug)
        name_toks = {w.strip(".").lower() for w in re.split(r"[\s\-\.]+", name) if len(w) >= 3}
        joined = re.sub(r"[^a-z]", "", name.lower())
        slug_joined = re.sub(r"[^a-z]", "", url_slug.lower())
        if toks and not (toks & name_toks) and slug_joined not in joined \
                and joined not in slug_joined:
            return None  # Slug shares no token with the name = a section heading, not a person name (review F1)

    if title_raw is None:
        for line in lines:  # Fallback: scan the full text (in the Monash php type the title is buried after the navigation)
            if (_TITLE_WORDS.search(line) and len(line) < 90
                    and "|" not in line and not looks_like_person_name(line)):
                title_raw = line
                break

    body_text = " ".join(lines)
    m = _arrival_re(tuple(arrival_inst_tokens)).search(body_text)
    arrival_hint = int(m.group(1)) if m else None

    return {"dept_key": dept_key, "display_name": name, "title_raw": title_raw,
            "sub_dept_hint": extract_sub_dept(title_raw),
            "arrival_hint_year": arrival_hint,
            "snapshot_year": int(timestamp[:4]), "timestamp": timestamp,
            "source_sha": source_sha}
