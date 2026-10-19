"""FirstPubAccumulator save/load (basis for resume): after loading, further add calls still take the correct min.

Resume requirement: pass A crashes midway -> on restart, read back the saved first-publication years ->
scan the remaining shards -> the merge still gives the full-history min.
Idempotence: load + continued adds gives the same result as one full scan (min is commutative and associative).
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from m1_ingest.first_pub import FirstPubAccumulator  # noqa: E402


def test_load_rows_restores_and_continues_min():
    a = FirstPubAccumulator()
    a.add(author_id="A1", publication_year=2010)
    a.add(author_id="A2", publication_year=2005)
    saved = a.rows()  # save = rows()

    b = FirstPubAccumulator()
    b.load_rows(saved)                                    # load
    b.add(author_id="A1", publication_year=2008)          # earlier -> must update to 2008
    b.add(author_id="A3", publication_year=2020)          # new author
    b.add(author_id="A2", publication_year=2009)          # later -> unchanged (still 2005)

    got = {r["author_id"]: r["first_pub_year"] for r in b.rows()}
    assert got == {"A1": 2008, "A2": 2005, "A3": 2020}


def test_resume_equals_onepass_full_scan():
    """Core invariant: save + resume == one full scan (identical first-publication year for every author)."""
    works = [
        ("A1", 2010), ("A2", 2005), ("A1", 2003), ("A3", 2015),
        ("A2", 2001), ("A4", 2018), ("A1", 2012), ("A3", 2011),
    ]
    # one full scan
    one = FirstPubAccumulator()
    for aid, y in works:
        one.add(author_id=aid, publication_year=y)
    one_map = {r["author_id"]: r["first_pub_year"] for r in one.rows()}

    # two segments with a save/load in between
    seg1 = FirstPubAccumulator()
    for aid, y in works[:4]:
        seg1.add(author_id=aid, publication_year=y)
    saved = seg1.rows()
    seg2 = FirstPubAccumulator()
    seg2.load_rows(saved)
    for aid, y in works[4:]:
        seg2.add(author_id=aid, publication_year=y)
    resume_map = {r["author_id"]: r["first_pub_year"] for r in seg2.rows()}

    assert resume_map == one_map, "A resumed run from the archive must give first-publication years per author identical to a single-pass scan"


def test_load_rows_skips_none_and_bad_id():
    b = FirstPubAccumulator()
    b.load_rows([{"author_id": None, "first_pub_year": 2000},
                 {"author_id": "A1", "first_pub_year": 2007}])
    got = {r["author_id"]: r["first_pub_year"] for r in b.rows()}
    assert got == {"A1": 2007}
