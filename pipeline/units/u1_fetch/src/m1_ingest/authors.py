"""M1-T-AUTH authors.py - AUTHORS table.

What it does:
  - collect {author_id, display_name, orcid} from authorships[].author -> write AUTHORS;
  - author_id is folded to its canonical id via canonical_id_map -> one person is not split (no duplicate PK);
  - several records for one canonical id: keep one of the distinct display_names and keep the orcid (if any record has one).

Conventions:
  - AUTHORS has 3 columns by default: {author_id, display_name, orcid}.
  - Open item: if the snapshot measured in m0 really contains display_name_alternatives, widening the table to 5 columns needs a separate,
    explicit change; this stage keeps 3 columns, and the column count follows the measured facts.

Official usage (OpenAlex authorships):
  author.id/display_name/orcid; ORCID is often null (the OpenAlex ids of Yves Zenou have no ORCID;
  an orcid may have been added by disambiguation). After canonicalisation the same person is merged, not split.

Red line: pure data shape, no identification rule; canonical ids are looked up in cmap only, and a missing id stays as the bare id (nothing is invented).
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from common.schema import AUTHORS
from m1_ingest._writer_util import bare, write_rows_parquet


class AuthorTable:
    """Accumulate author rows + fold to canonical ids -> one row per person.

    author_cmap = {raw_id: canonical_id} (replay of M0 merged_ids); add() folds author_id to its canonical id.
    Several add() calls for one canonical id:
      - display_name: the first non-empty value is kept (a later None does not overwrite; a later non-empty value fills an empty one);
      - orcid: kept if any record has one (None does not overwrite an existing orcid).
    """

    def __init__(self, *, author_cmap: Optional[Mapping[str, str]] = None):
        self._cmap = author_cmap or {}
        # canonical_id → {"display_name":.., "orcid":..}
        self._by_id: dict[str, dict] = {}
        # Keep insertion order (deterministic); the writer sorts by author_id when writing.
        self._order: list[str] = []

    def add(self, *, author_id, display_name=None, orcid=None) -> None:
        cid = bare(author_id)
        if cid is None:
            return
        cid = self._cmap.get(cid, cid)
        if cid not in self._by_id:
            self._by_id[cid] = {"display_name": display_name, "orcid": orcid}
            self._order.append(cid)
            return
        cur = self._by_id[cid]
        # display_name: existing empty and new non-empty -> fill in; existing non-empty -> keep (not overwritten by None or a later value).
        if cur["display_name"] is None and display_name is not None:
            cur["display_name"] = display_name
        # orcid: existing empty and new non-empty -> fill in (keep distinct, prefer a non-empty value).
        if cur["orcid"] is None and orcid is not None:
            cur["orcid"] = orcid

    def add_author(self, author: dict) -> None:
        """Convenience: feed directly from an authorships[].author dict."""
        if not author:
            return
        self.add(
            author_id=author.get("id"),
            display_name=author.get("display_name"),
            orcid=author.get("orcid"),
        )

    def rows(self) -> list[dict]:
        """Export the AUTHORS 3-column rows (insertion order; the writer sorts when writing)."""
        return [
            {
                "author_id": cid,
                "display_name": self._by_id[cid]["display_name"],
                "orcid": self._by_id[cid]["orcid"],
            }
            for cid in self._order
        ]

    def write(self, target) -> None:
        write_authors(self.rows(), target)


def write_authors(rows: Iterable[dict], target) -> None:
    """Write the AUTHORS parquet (PK=author_id; deterministic, schema check before writing, exactly 3 columns)."""
    write_rows_parquet(
        rows, target,
        schema=AUTHORS,
        pk_cols=("author_id",),
        label="AUTHORS",
    )
