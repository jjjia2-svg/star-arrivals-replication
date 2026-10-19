"""TDD red tests for U0 dose.py.

Guards the interface contract:
  - C.5: coupling_share (main dose, shared-reference coupling up to t-1, #16) /
    topic_cos / embed_cos (secondary dose, never enters dose_coupling).
  - coupling_share(refs_a:set, refs_b:set, ref_idf:dict|None=None) -> float
  - topic_cos(vec_a:dict, vec_b:dict) -> float  (sorted keys + math.fsum, deterministic)
  - embed_cos(vec_a:list, vec_b:list) -> float  (math.fsum)
  - unit test of coupling_share: "symmetry + hub-ref down-weighting".
  - identity rule: no IO / no network / no state.

Rule: dose.coupling_normalization = cosine (configured in RED, not left as a null placeholder).
  coupling_share reads the configured value from RED and proceeds; the guard "null -> raise, not decided here" is unchanged
  (the first test in test_coupling_share checks that the configured value is read as is; u5 test_coupling has a separate
  monkeypatch-None guard test). The structural properties (symmetry / range / empty set) are still run by
  temporarily switching to jaccard with monkeypatch (rule-independent invariants), and the tests do not pin the normalisation formula.

Plain words:
  coupling_share (bibliographic-coupling share) = how many of the same references two people cite -> how close their knowledge is -> how high the dose.
  topic_cos / embed_cos = cosine similarity of topic vectors / abstract vectors (secondary signal).

These tests are purely local, with no network and no data fetching.
"""
import math
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from common._redlines import RED  # noqa: E402
from identity import dose  # noqa: E402


# ============ coupling_share: the configured normalisation is read as is ============

def test_coupling_share_reads_signed_cosine_from_yaml():
    # Without injecting anything, read the value set in the YAML ->
    # cosine normalisation = |A∩B| / sqrt(|A|·|B|) = 1 / sqrt(2·2) = 0.5.
    # The mechanism "null -> raise, not decided here" is kept (see the identity.dose require path +
    # the monkeypatch-None guard test in u5 test_coupling).
    assert RED["dose"]["coupling_normalization"] == "cosine"  # guards the current configured value
    assert dose.coupling_share({"r1", "r2"}, {"r1", "r3"}) == 0.5


# The symmetry / range / empty-set tests below temporarily set a known mode (jaccard) to run structural properties;
# this does not mean the rule is jaccard, it only verifies rule-independent invariants (symmetry / range / empty set).
@pytest.fixture
def _signed_jaccard(monkeypatch):
    monkeypatch.setitem(RED["dose"], "coupling_normalization", "jaccard")
    monkeypatch.setitem(RED["dose"], "hub_ref_idf_floor", 0.0)
    monkeypatch.setitem(RED["dose"], "coverage_floor", 0.0)
    return None


def test_coupling_share_symmetric(_signed_jaccard):
    # symmetry: share(A,B) == share(B,A)
    a = {"r1", "r2", "r3"}
    b = {"r2", "r3", "r4"}
    assert dose.coupling_share(a, b) == dose.coupling_share(b, a)


def test_coupling_share_in_unit_range(_signed_jaccard):
    a = {"r1", "r2", "r3"}
    b = {"r2", "r3", "r4"}
    v = dose.coupling_share(a, b)
    assert 0.0 <= v <= 1.0


def test_coupling_share_identical_sets_is_one(_signed_jaccard):
    a = {"r1", "r2", "r3"}
    assert dose.coupling_share(a, set(a)) == 1.0


def test_coupling_share_disjoint_is_zero(_signed_jaccard):
    assert dose.coupling_share({"r1", "r2"}, {"r3", "r4"}) == 0.0


def test_coupling_share_both_empty_is_zero(_signed_jaccard):
    # neither side has references -> 0 (no sharing; no NaN, no division-by-zero crash)
    assert dose.coupling_share(set(), set()) == 0.0


def test_coupling_share_one_empty_is_zero(_signed_jaccard):
    assert dose.coupling_share({"r1"}, set()) == 0.0


def test_coupling_share_returns_float(_signed_jaccard):
    assert isinstance(dose.coupling_share({"r1"}, {"r1"}), float)


def test_coupling_share_idf_weighted_symmetric(_signed_jaccard):
    # still symmetric with ref_idf (hub-ref down-weighting path)
    a = {"r1", "r2"}
    b = {"r2", "r3"}
    idf = {"r1": 2.0, "r2": 0.5, "r3": 1.5}  # r2 = hub-ref, low weight
    assert dose.coupling_share(a, b, idf) == dose.coupling_share(b, a, idf)


def test_coupling_share_none_input_raises(_signed_jaccard):
    # refs is None (upstream did not fetch them) -> raise, never silently treated as an empty set
    with pytest.raises((ValueError, TypeError)):
        dose.coupling_share(None, {"r1"})


# ============ topic_cos: cosine of dict vectors, sorted keys + fsum (deterministic) ============

def test_topic_cos_identical_is_one():
    v = {"t1": 1.0, "t2": 2.0}
    assert math.isclose(dose.topic_cos(v, dict(v)), 1.0, rel_tol=1e-12)


def test_topic_cos_orthogonal_is_zero():
    a = {"t1": 1.0}
    b = {"t2": 1.0}
    assert dose.topic_cos(a, b) == 0.0


def test_topic_cos_symmetric():
    a = {"t1": 1.0, "t2": 2.0, "t3": 3.0}
    b = {"t2": 1.0, "t3": 1.0, "t4": 5.0}
    assert dose.topic_cos(a, b) == dose.topic_cos(b, a)


def test_topic_cos_in_unit_range():
    a = {"t1": 1.0, "t2": 2.0}
    b = {"t1": 2.0, "t2": 1.0}
    v = dose.topic_cos(a, b)
    assert 0.0 <= v <= 1.0 + 1e-12


def test_topic_cos_empty_vector_is_zero():
    # empty vector -> 0 (no division-by-zero crash)
    assert dose.topic_cos({}, {"t1": 1.0}) == 0.0
    assert dose.topic_cos({}, {}) == 0.0


def test_topic_cos_returns_float():
    assert isinstance(dose.topic_cos({"t1": 1.0}, {"t1": 1.0}), float)


# ============ embed_cos: cosine of list vectors, fsum ============

def test_embed_cos_identical_is_one():
    v = [1.0, 2.0, 3.0]
    assert math.isclose(dose.embed_cos(v, list(v)), 1.0, rel_tol=1e-12)


def test_embed_cos_orthogonal_is_zero():
    assert dose.embed_cos([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_embed_cos_symmetric():
    a = [1.0, 2.0, 3.0]
    b = [3.0, 1.0, 2.0]
    assert dose.embed_cos(a, b) == dose.embed_cos(b, a)


def test_embed_cos_length_mismatch_raises():
    # mismatched dimensions = an upstream bug: fail loudly, never silently pad with zeros
    with pytest.raises((ValueError, IndexError)):
        dose.embed_cos([1.0, 2.0], [1.0, 2.0, 3.0])


def test_embed_cos_zero_vector_is_zero():
    assert dose.embed_cos([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_embed_cos_returns_float():
    assert isinstance(dose.embed_cos([1.0], [1.0]), float)
