"""U6Inputs: input handles for the assembly layer (nine read-only sources; contract as code, aligned table by table with the u0 schema).

Fields (all list[dict] / dict, filled by io_real (real data) or by test fixtures (synthetic)):
  person_map  PERSON_MAP rows (U2)
  star_set    current 14-column rows (U4; key = OpenAlex author_id)
  events      EVENTS 11-column rows (U4; the star_person_id column holds the raw author_id, as on disk)
  dose        {"p01"|"p05": PAIRWISE_DOSE 11-column rows} (U5)
  output      {"p01"|"p05": OUTPUT 12-key rows} (U5; p01 = version excluding 1% stars / p05 = version excluding 5% stars)
  roster      table B DEPT_ROSTER_PANEL 8-column rows (U0.5, both departments in one table)
  registry    table A ECON_DEPT_REGISTRY 10-column rows (U0.5)
  panel       U3 panel slice, 5 columns {person_id, year, primary_affil_id,
              n_works_year, first_pub_year} (a projection, not all 8 columns)
  work_first_pub  {author_id: first_pub_year} fallback (the real career history from U1, used when the panel lacks a person)
  upstream_provenance  {"u4": 4-tuple, "u5": 4-tuple} (double anchor)
  upstream_diag        U5 dose/output diag (MNAR double flag passed through)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class U6Inputs:
    person_map: list = field(default_factory=list)
    star_set: list = field(default_factory=list)
    events: list = field(default_factory=list)
    dose: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    roster: list = field(default_factory=list)
    registry: list = field(default_factory=list)
    panel: list = field(default_factory=list)
    work_first_pub: dict = field(default_factory=dict)
    upstream_provenance: dict = field(default_factory=dict)
    upstream_diag: dict = field(default_factory=dict)
    report: dict = field(default_factory=dict)

    def pid_by_author(self) -> dict[str, str]:
        return {r["author_id"]: r["person_id"] for r in self.person_map}

    def star_by_author(self) -> dict[str, dict]:
        return {r["author_id"]: r for r in self.star_set}

    def events_by_id(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for e in self.events:
            if e["event_id"] in out:
                raise ValueError(f"duplicate EVENTS PK: {e['event_id']!r}")
            out[e["event_id"]] = e
        return out
