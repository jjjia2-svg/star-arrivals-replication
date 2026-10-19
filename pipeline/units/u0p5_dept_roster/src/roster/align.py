"""U0.5 step 2: author_id alignment - person name -> OpenAlex bare author_id.

Two parts:
  1. classify_match() - a pure decision (testable offline): given an /authors response, decide
     1 hit / 0 hits / several hits -> (bare author_id or None, confidence, needs_human).
     Red line #1: 0 or several hits -> needs_human=True, never guess an id.
  2. search_author() - the live fetch (thin wrapper): curl/requests OpenAlex /authors,
     mailto polite pool + api_key + throttling (<= 8 req/s) + exponential back-off on 429.

Official usage (OpenAlex documentation):
  - authentication: mailto= joins the polite pool (strongly recommended); api_key= raises the quota.
  - rate limit: exceeding it gives HTTP 429; read X-RateLimit-Remaining to slow down proactively; back off exponentially on 429.
  - main alignment: filter=display_name.search:<name>,last_known_institutions.id:I56590836;
    an empty result -> search by name without the institution and check whether the topics fall in subfield 2002.
  - red line #3: never read affiliations[].years to decide any year (this step does not fetch years at all).

Rules: bare author_id (no URL prefix; the table B author_id column requires it); 0 or several hits are flagged needs_human;
  raw author_id (not person_id; U2 folds downstream); polite rate limiting.
"""
from __future__ import annotations

import time
import urllib.parse
from typing import Optional

from common._redlines import require

# ---- fixed constants ----
MAILTO = "jjjia2@student.unimelb.edu.au"          # polite pool (④)
MONASH_INST_ID = "I56590836"                       # Monash university-level institution id (bare, verified live)
UNSW_INST_ID = "I31746571"                         # UNSW Sydney university-level institution id (bare; ROR 03r8z3t63
                                                   #   verified live: country_code=AU / type=education;
                                                   #   table A unsw_econ.openalex_inst_id, to be checked by hand)
# The subfield whitelist is consumed from redlines (one true source, shared with byline_skeleton; editing the YAML is picked up automatically,
# and multiple include codes are supported naturally - a scalar == cannot express parallel codes). redlines.yaml is not changed; the code only reads it.
ECON_SUBFIELDS: frozenset[str] = frozenset(require("subfield_whitelist", "include"))
OPENALEX_AUTHORS_ENDPOINT = "https://api.openalex.org/authors"
OPENALEX_URL_PREFIX = "https://openalex.org/"

# ---- polite rate-limit parameters ----
MAX_REQ_PER_SEC = 8                                # <= 8 req/s (the official limit is <= 100; this project limits itself conservatively)
_MIN_INTERVAL_SEC = 1.0 / MAX_REQ_PER_SEC          # minimum interval per request
RETRY_MAX = 4                                      # maximum number of retries on 429
RETRY_BACKOFF_BASE_SEC = 3.0                       # first back-off 3 s, then doubling (3/6/12/24)

# ---- works_count dominance threshold (the 16-fragment case of Yves Zenou: the real author has 583 works vs <= 5 for same-name fragments, 116x) ----
# This is a heuristic for anchoring the U0.5 raw author_id (the threshold is provisional): when >= 2 same-name hits all fall in economics subfield 2002,
#   and the highest works_count >= DOMINANCE_RATIO x the runner-up -> take the dominant one (confidence=low, pending a human check + U2 folding).
#   Below the threshold -> needs_human (red line #1: never guess where it is ambiguous). Folding 16 -> 1 is U2's job; U0.5 anchors only the main raw fragment.
DOMINANCE_RATIO = 20                               # >= 20x counts as "decisive dominance" (Yves Zenou measured 116x, leaving ample margin)


def _bare(oid: Optional[str]) -> Optional[str]:
    """OpenAlex id URL -> bare id (strip the https://openalex.org/ prefix). None/"" -> None."""
    if not oid:
        return None
    s = str(oid)
    return s[len(OPENALEX_URL_PREFIX):] if s.startswith(OPENALEX_URL_PREFIX) else s


def _subfield_of(result: dict) -> Optional[str]:
    """Take the main subfield's bare id (e.g. "2002") from the topics of an author result.

    An OpenAlex author has no top-level subfield; use the tail segment of topics[0].subfield.id (a URL).
    Missing -> None. (topic-ID int->str migration: always take the tail segment of the URL string.)
    """
    topics = result.get("topics") or []
    if not topics:
        return None
    sub = (topics[0] or {}).get("subfield") or {}
    sid = sub.get("id")
    if not sid:
        return None
    # normalise: URL / "subfields/2002" / "2002" -> "2002".
    return str(sid).rsplit("/", 1)[-1]


def _works_count(result: dict) -> int:
    """Get works_count of an author result (missing -> 0)."""
    wc = result.get("works_count")
    return int(wc) if isinstance(wc, (int, float)) else 0


def _resolve_econ_multi(econ_hits: list) -> dict:
    """When >= 2 hits all fall in economics subfield 2002, converge using works_count dominance.

    - exactly 1 falls in 2002 -> take it (medium).
    - >= 2 fall in 2002:
        * highest works_count >= DOMINANCE_RATIO x the runner-up -> take the dominant one (confidence=low,
          a heuristic anchor on the main raw fragment, pending a human check + U2 folding; the Yves Zenou 16-fragment case);
        * otherwise (not dominant enough) -> needs_human (red line #1: never guess where it is ambiguous).
    - 0 fall in 2002 -> needs_human.
    """
    if len(econ_hits) == 1:
        return {"author_id": _bare(econ_hits[0].get("id")), "confidence": "medium", "needs_human": False}
    if len(econ_hits) == 0:
        return {"author_id": None, "confidence": None, "needs_human": True}

    ranked = sorted(econ_hits, key=_works_count, reverse=True)
    top, runner_up = ranked[0], ranked[1]
    top_wc, ru_wc = _works_count(top), _works_count(runner_up)
    if top_wc > 0 and top_wc >= DOMINANCE_RATIO * max(1, ru_wc):
        # decisive dominance -> anchor the dominant fragment (low confidence, pending a human check / U2 folding).
        return {"author_id": _bare(top.get("id")), "confidence": "low", "needs_human": False}
    return {"author_id": None, "confidence": None, "needs_human": True}


def classify_match(results: list, *, used_institution_filter: bool) -> dict:
    """OpenAlex /authors response -> alignment decision (pure function, testable offline).

    Inputs:
      results - the results list of /authors (each item has id and may have topics, works_count).
      used_institution_filter - whether this search carried the last_known_institutions.id institution filter.
        True  = main alignment (institution-restricted); 1 hit -> high.
        False = fallback search by name without the institution; 1 hit -> medium.

    Returns: {author_id: bare|None, confidence: high/medium/low|None, needs_human: bool}

    Decision (red line #1: 0 or several hits without decisive dominance -> needs_human, never guess):
      - exactly 1 hit:
          * with the institution filter -> high (institution and name both lock); without -> medium (name only).
      - 0 hits -> needs_human.
      - >= 2 hits -> converge on economics subfield 2002 (_resolve_econ_multi):
          exactly 1 in 2002 -> take it (medium);
          >= 2 in 2002 + decisive works_count dominance (>= DOMINANCE_RATIO x the runner-up) -> take the dominant one (low);
          otherwise -> needs_human.
          (Yves Zenou's 16 fragments: the institution filter also returns 4 non-canonical fragments -> this dominance step converges on the main fragment with 583 works;
           folding 16 -> 1 is U2's job, U0.5 anchors only the main raw fragment.)
    """
    n = len(results)

    if n == 1:
        return {
            "author_id": _bare(results[0].get("id")),
            "confidence": "high" if used_institution_filter else "medium",
            "needs_human": False,
        }

    if n == 0:
        return {"author_id": None, "confidence": None, "needs_human": True}

    # n >= 2: with or without the institution filter, converge using the economics subfield + works_count dominance
    # (for Yves Zenou the institution filter also returns 4 non-canonical fragments -> only dominance, not "trust the institution filter", anchors the right one).
    econ_hits = [r for r in results if _subfield_of(r) in ECON_SUBFIELDS]
    return _resolve_econ_multi(econ_hits)


# ===========================================================================
# live fetch thin wrapper (real OpenAlex; polite rate limiting + 429 back-off)
# ===========================================================================
class _Throttle:
    """Global throttle: guarantees adjacent requests are >= _MIN_INTERVAL_SEC apart (<= 8 req/s)."""

    def __init__(self):
        self._last = 0.0

    def wait(self):
        now = time.monotonic()
        gap = now - self._last
        if gap < _MIN_INTERVAL_SEC:
            time.sleep(_MIN_INTERVAL_SEC - gap)
        self._last = time.monotonic()


_THROTTLE = _Throttle()


# Fetch only the fields needed for alignment + dominance convergence (saves bandwidth; works_count is essential for dominance; topics gives the subfield).
# Never fetch affiliations (red line #3: never read affiliations[].years to decide any year).
_SELECT_FIELDS = "id,display_name,works_count,topics"


def _build_url(display_name: str, *, use_institution_filter: bool, inst_id: str = MONASH_INST_ID) -> str:
    """Build the /authors query URL (display_name.search + optional institution filter + mailto + select).

    inst_id: the university-level bare id used for the institution-restricted search (default Monash; the UNSW slice passes UNSW_INST_ID).
      The Monash default keeps backward compatibility and does not break the existing Monash slice.
    """
    name_enc = urllib.parse.quote(display_name)
    if use_institution_filter:
        flt = f"display_name.search:{name_enc},last_known_institutions.id:{inst_id}"
    else:
        flt = f"display_name.search:{name_enc}"
    return (
        f"{OPENALEX_AUTHORS_ENDPOINT}?filter={flt}"
        f"&select={_SELECT_FIELDS}&mailto={MAILTO}&per-page=50"
    )


def _get_json(url: str, *, api_key: Optional[str]):
    """GET with throttling + exponential back-off on 429 -> JSON dict.

    - every request passes the throttle first (<= 8 req/s);
    - api_key goes in as a query parameter (the documented method; no header method is given);
    - 429 -> retry with exponential back-off (RETRY_BACKOFF_BASE * 2**i), at most RETRY_MAX times;
    - any other non-200 -> raise (let the caller decide).
    """
    import requests  # local import: the pure-decision tests do not need requests

    full = url
    if api_key:
        full = f"{url}&api_key={urllib.parse.quote(api_key)}"

    last_exc = None
    for attempt in range(RETRY_MAX + 1):
        _THROTTLE.wait()
        resp = requests.get(full, timeout=30)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            # rate limit: retry after exponential back-off.
            wait_s = RETRY_BACKOFF_BASE_SEC * (2 ** attempt)
            last_exc = RuntimeError(f"429 rate-limited (attempt {attempt}); backing off {wait_s}s")
            time.sleep(wait_s)
            continue
        resp.raise_for_status()
    raise last_exc or RuntimeError("exhausted retries")


def search_author(display_name: str, *, api_key: Optional[str] = None, inst_id: str = MONASH_INST_ID) -> dict:
    """For one person name, do the main alignment + fallback and return the classify_match decision (a real live call).

    Flow:
      1. Institution-restricted search (last_known_institutions.id:inst_id). Hit -> classify (high).
      2. Restricted search empty -> search by name without the institution + subfield 2002 convergence -> classify (medium).

    inst_id: the university-level bare id used for the institution-restricted search (default Monash; the UNSW slice passes UNSW_INST_ID).
      Route 2 (search by name without the institution + global subfield 2002 dominance convergence) does not depend on the institution -> both universities use the same definition.

    Returns the decision dict of classify_match (with author_id/confidence/needs_human),
    plus search_path recording how this result was reached (audit/reproduction).
    Never reads affiliations[].years (red line #3).

    Yves Zenou (measured live): the institution-restricted search returns 4 non-canonical fragments (works <= 5) -> classify
      still gives needs_human after dominance convergence -> it must **fall through to route 2** (name only; the canonical A5017376589
      with 583 works is found there) to anchor correctly. So when route 1 gives needs_human it does not return early but continues to route 2.
    """
    # --- route 1: institution-restricted ---
    # Trust it only when the restricted search returns **exactly 1 hit** (a real institution + name double lock, cleanest -> high).
    #   >= 2 hits = the name is also fragmented under that institution (Yves Zenou: 4 non-canonical fragments, the only
    #   econ one internally is a 5-works false winner) -> this **biased small set** is not trustworthy; fall to route 2 and anchor by **global** dominance.
    url1 = _build_url(display_name, use_institution_filter=True, inst_id=inst_id)
    data1 = _get_json(url1, api_key=api_key)
    results1 = data1.get("results") or []
    if len(results1) == 1:
        verdict = classify_match(results1, used_institution_filter=True)
        verdict["search_path"] = "institution_filtered"
        return verdict
    # >= 2 hits (or 0 hits) -> fall to the route-2 global anchor (Yves Zenou's canonical A5017376589 with 583 works is found there).

    # --- route 2: search by name without the institution + subfield / global works_count dominance convergence ---
    url2 = _build_url(display_name, use_institution_filter=False, inst_id=inst_id)
    data2 = _get_json(url2, api_key=api_key)
    results2 = data2.get("results") or []
    verdict = classify_match(results2, used_institution_filter=False)
    verdict["search_path"] = "name_only_subfield"
    return verdict
