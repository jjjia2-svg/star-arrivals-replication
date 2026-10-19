"""M1-T-INST institutions.py - INSTITUTIONS table (a first-class product).

What it does:
  - from works.authorships[].institutions[] (dehydrated), emit one row per distinct institution;
  - write the 7 INSTITUTIONS columns (institution_id, display_name, country_code, type, lineage,
    associated_institutions:list<dict>, ror);
  - includes ALL foreign institutions (no in_au filter): foreign institutions of Yves Zenou such as Stockholm/IFN/IZA (country != AU)
    must also be in the table, otherwise U3 cannot determine the arrival switch point and those institutions go missing
    (a test case for Yves Zenou).

Official usage (OpenAlex authorships):
  authorships[].institutions[] = dehydrated, with id / ror / country_code / type / lineage;
  often empty (small institutions / odd affiliation strings fail to match) -> this table keeps only institutions that really appear;
  the fallback for empty institutions is the raw_affil of works_affil.

Alignment with U0 INSTITUTIONS (display_name + country_code added = 7 columns):
  - country_code comes from the country_code field of the institution record; it is only for downstream foreign-institution checks and readability,
    fold_to_canonical does not read it.
  - associated_institutions stays list<dict> (fold_to_canonical path3 reads assoc.relationship/type/id;
    list<str> would lose them -> never change it to list<str>).
  - the column name stays type (not inst_type).

Red line: pure data shape, no identification rule; no institution filtering at all (in_au is decided in U3/U6).
"""
from __future__ import annotations

from typing import Iterable, Iterator

from common.schema import INSTITUTIONS
from m1_ingest._writer_util import bare, write_rows_parquet

# Every dict in associated_institutions is normalised to this set of keys (path3 reads only id/relationship/type).
# Fixed key set -> consistent struct across rows, so parquet can be written deterministically.
_ASSOC_KEYS = ("id", "relationship", "type")


def _norm_assoc(assoc_list) -> list[dict]:
    """associated_institutions list -> each item normalised to the fixed keys {id, relationship, type}.

    - None -> [];
    - id goes through bare (same space as the institution primary key); relationship/type unchanged (missing -> None);
    - keeps the list<dict> shape (fold_to_canonical path3 reads these three keys), never flattened into list<str>.
    """
    if not assoc_list:
        return []
    out = []
    for a in assoc_list:
        if not isinstance(a, dict):
            continue
        out.append({
            "id": bare(a.get("id")),
            "relationship": a.get("relationship"),
            "type": a.get("type"),
        })
    return out


def flatten_institution(inst: dict) -> dict:
    """One dehydrated institution -> INSTITUTIONS 7-column row (single authoritative implementation; schema_map re-exports this function).

    - institution_id: bare(inst["id"]);
    - display_name / country_code / type / ror: unchanged (missing -> None);
    - lineage: each item made bare (the chain is not flattened, only the URL prefix is stripped). The chain is what fold_to_canonical path2 depends on;
      everything is in the bare-id space (consistent with institution_id / associated_institutions[].id / registry keys);
      fold_to_canonical's internal _bare accepts both forms, but storing bare uniformly in this table avoids drifting from the id space (DRY);
    - associated_institutions: _norm_assoc (list<dict>, what path3 depends on).
    """
    return {
        "institution_id": bare(inst.get("id")),
        "display_name": inst.get("display_name"),
        "country_code": inst.get("country_code"),
        "type": inst.get("type"),
        "lineage": [bare(x) for x in (inst.get("lineage") or [])],
        "associated_institutions": _norm_assoc(inst.get("associated_institutions")),
        "ror": inst.get("ror"),
    }


def iter_institutions(work: dict) -> Iterator[dict]:
    """One work -> one row per institution inside its authorships[].institutions[] (foreign included, no filtering).

    An institution that appears several times in one work is yielded each time (de-duplication by institution_id is left to run_m1).
    Empty institutions -> no row (this table keeps only real institutions).
    """
    for authorship in work.get("authorships") or []:
        for inst in authorship.get("institutions") or []:
            if inst is None:
                continue
            yield flatten_institution(inst)


def write_institutions(rows: Iterable[dict], target) -> None:
    """Write the INSTITUTIONS parquet (PK=institution_id; deterministic, schema check before writing)."""
    write_rows_parquet(
        rows, target,
        schema=INSTITUTIONS,
        pk_cols=("institution_id",),
        label="INSTITUTIONS",
    )
