"""M7a stock_query — duckdb query computing each author's citation stock + subfield per year on real data (definition A).

Reference pool = **all author_id** (does not join the internal person_map). The ranked entity = OpenAlex author_id,
which the downstream classify_all_cells calls person_id generically. The tests use small in-memory duckdb data to check consistency with the atomic semantics of the pure functions
(full counting, cumulative, missing values never silently treated as 0).
"""
import pytest


def _con():
    duckdb = pytest.importorskip("duckdb")
    con = duckdb.connect()
    con.execute("CREATE TABLE works(work_id VARCHAR, publication_year INTEGER, cited_by_count INTEGER, subfield_id VARCHAR)")
    con.execute("CREATE TABLE authorship_edges(work_id VARCHAR, author_id VARCHAR)")
    return con


def _w(con, rows):
    """rows = [(work_id, year, cites, subfield)] → insert into works (including subfield)."""
    con.executemany("INSERT INTO works VALUES (?,?,?,?)", rows)


def test_cumulative_stock_full_count():
    """Per author per year = cumulative raw citation sum up to that year (inclusive) (full counting)."""
    from m7a_star.stock_query import PERSON_YEAR_STOCK_SQL
    con = _con()
    con.execute("INSERT INTO works(work_id,publication_year,cited_by_count) VALUES ('w1',2010,5),('w2',2012,3),('w3',2015,100)")
    con.execute("INSERT INTO authorship_edges VALUES ('w1','a1'),('w2','a1'),('w3','a1')")
    d = {(a, yr): stock for a, yr, stock in con.execute(PERSON_YEAR_STOCK_SQL).fetchall()}
    assert d[("a1", 2010)] == 5      # up to 2010: 5
    assert d[("a1", 2012)] == 8      # up to 2012: 5+3 cumulative
    assert d[("a1", 2015)] == 108    # up to 2015: 5+3+100 cumulative


def test_full_count_not_fractional_when_coauthored():
    """A 3-author paper with 30 citations → each author gets the full 30 (full counting, no splitting)."""
    from m7a_star.stock_query import PERSON_YEAR_STOCK_SQL
    con = _con()
    con.execute("INSERT INTO works(work_id,publication_year,cited_by_count) VALUES ('w1',2010,30)")
    con.execute("INSERT INTO authorship_edges VALUES ('w1','a1'),('w1','a2'),('w1','a3')")
    d = {(a, yr): stock for a, yr, stock in con.execute(PERSON_YEAR_STOCK_SQL).fetchall()}
    assert d[("a1", 2010)] == 30 and d[("a2", 2010)] == 30 and d[("a3", 2010)] == 30


def test_two_authors_ranked_by_stock():
    """Two authors accumulate separately, independent of each other."""
    from m7a_star.stock_query import PERSON_YEAR_STOCK_SQL
    con = _con()
    con.execute("INSERT INTO works(work_id,publication_year,cited_by_count) VALUES ('w1',2010,500),('w2',2010,2)")
    con.execute("INSERT INTO authorship_edges VALUES ('w1','big'),('w2','small')")
    d = {(a, yr): stock for a, yr, stock in con.execute(PERSON_YEAR_STOCK_SQL).fetchall()}
    assert d[("big", 2010)] == 500 and d[("small", 2010)] == 2


def test_person_year_modal_subfield_ties_min():
    """author×year subfield = the mode of that year's papers; ties take the smallest id (lexicographic) (S8-3)."""
    from m7a_star.stock_query import PERSON_YEAR_SUBFIELD_SQL
    con = _con()
    # a 2010: 2 papers '2002' + 1 paper '2010' → mode 2002
    # a 2011: 1 paper '2010' + 1 paper '2002' (tie) → smaller id = 2002
    _w(con, [("w1", 2010, 5, "2002"), ("w2", 2010, 3, "2002"), ("w3", 2010, 1, "2010"),
             ("w4", 2011, 4, "2010"), ("w5", 2011, 2, "2002")])
    con.execute("INSERT INTO authorship_edges VALUES ('w1','a'),('w2','a'),('w3','a'),('w4','a'),('w5','a')")
    d = {(a, y): sf for a, y, sf in con.execute(PERSON_YEAR_SUBFIELD_SQL).fetchall()}
    assert d[("a", 2010)] == "2002"   # mode
    assert d[("a", 2011)] == "2002"   # tie → smallest id
