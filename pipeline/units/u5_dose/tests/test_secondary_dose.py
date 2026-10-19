"""Secondary dose (topic_vec + embed) red tests: cases #20/#21/#22/#23.

The secondary dose (topic_cos / embed_cos) is only a robustness check and **never enters the primary dose coupling_share** (#16).
#22 source guard: the four primary-path modules (cutoff/candidate_pairs/degree2_closure/coupling) never touch
abstract/embedding/topic, so the isolation is physical, at the file level.
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest

from common.manifest import sha256_file
from m4_dose import embed, topic_vec


def _pedges(triples):
    return [{"work_id": w, "person_id": p, "publication_year": y} for w, p, y in triples]


def _det_embedder(text: str):
    """Deterministic sentence vector for tests: the first 8 bytes of sha256 -> an 8-dim [0,1] vector (no external model dependency).

    The real model (config knobs such as embed_model_name/embed_seed) is injected at the run level;
    this unit tests the freeze/reproduce/HALT machinery, decoupled from the model implementation.
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255.0 for b in digest[:8]]


# ---------------------------------------------------------------------------
# #20 entry schema: WORK_TEXT 3 columns {work_id, title, abstract_text}
# ---------------------------------------------------------------------------
def test_abstract_required_for_secondary_embed(mk):
    """#20: work_text missing the abstract_text column -> raise; the entry validates the 3-column WORK_TEXT schema
    (not the old has_abstract version)."""
    bad_rows = [{"work_id": "W1", "title": "t"}]  # abstract_text missing
    with pytest.raises(Exception):
        embed.embed_works(bad_rows, embedder=_det_embedder, model_sha="m_test")

    old_style = [{"work_id": "W1", "title": "t", "abstract_text": "a",
                  "has_abstract": True}]  # Old column mixed in -> the key set is not exact -> raise
    with pytest.raises(Exception):
        embed.embed_works(old_style, embedder=_det_embedder, model_sha="m_test")


def test_abstract_none_value_raises(mk):
    """abstract_text=None -> raise (a missing secondary-dose input is never silently filled with an empty string)."""
    rows = [{"work_id": "W1", "title": "t", "abstract_text": None}]
    with pytest.raises(ValueError):
        embed.embed_works(rows, embedder=_det_embedder, model_sha="m_test")


# ---------------------------------------------------------------------------
# #21 freeze + determinism + mismatch HALT
# ---------------------------------------------------------------------------
def test_embed_deterministic_same_env(tmp_path, mk):
    """#21a: two runs in the same environment -> work_embeddings.parquet is byte-identical (determinism at atol=0)."""
    rows = [mk.text("W2", abstract_text="beta"), mk.text("W1", abstract_text="alpha")]
    outs = []
    for run in range(2):
        emb_rows = embed.embed_works(rows, embedder=_det_embedder, model_sha="m_test")
        target = tmp_path / f"run{run}" / "work_embeddings.parquet"
        embed.write_frozen_embeddings(emb_rows, target)
        outs.append(sha256_file(target))
    assert outs[0] == outs[1]


def test_embed_reads_frozen_halts_on_mismatch(tmp_path, mk):
    """#21b: frozen-vector model_sha differs from the expected one -> EmbeddingModelMismatch (HALT, not a silent recompute)."""
    rows = [mk.text("W1", abstract_text="alpha")]
    emb_rows = embed.embed_works(rows, embedder=_det_embedder, model_sha="m_v1")
    target = tmp_path / "work_embeddings.parquet"
    embed.write_frozen_embeddings(emb_rows, target)

    ok = embed.load_frozen_embeddings(target, expected_model_sha="m_v1")
    assert set(ok.keys()) == {"W1"}
    with pytest.raises(embed.EmbeddingModelMismatch):
        embed.load_frozen_embeddings(target, expected_model_sha="m_v2")


def test_person_embed_vec_frozen_mean(mk):
    """Person vector = per-dimension mean (deterministic fsum) of work vectors up to t-1; no works -> None."""
    edges = _pedges([("W1", "P_A", 2014), ("W2", "P_A", 2015), ("W3", "P_A", 2016)])
    emb = {"W1": [0.0, 1.0], "W2": [1.0, 0.0], "W3": [9.0, 9.0]}
    vec = embed.person_embed_vec("P_A", edges, emb, 2015)
    assert vec == [0.5, 0.5]  # W3 (2016) is beyond the freeze point
    assert embed.person_embed_vec("P_NONE", edges, emb, 2015) is None


# ---------------------------------------------------------------------------
# #23 subfield safety net + topic-ID dual-format normalization
# ---------------------------------------------------------------------------
def test_subfield_available_gate(mk):
    """#23a (B-SUBF safety net): subfield_id=None for all works -> raise; present -> pass."""
    ok_rows = [mk.work("W1", 2014, subfield_id="2002")]
    topic_vec.assert_subfield_available(ok_rows)  # Does not raise
    none_rows = [mk.work("W1", 2014, subfield_id=None)]
    with pytest.raises(topic_vec.SubfieldUnavailable):
        topic_vec.assert_subfield_available(none_rows)
    with pytest.raises(topic_vec.SubfieldUnavailable):
        topic_vec.assert_subfield_available([{"work_id": "W1"}])  # The column is missing altogether


def test_subfield_id_canonicalized():
    """#23b: int 2002 / 'subfields/2002' / a full URL normalize to the same canonical key and are never compared raw."""
    forms = [2002, "2002", "subfields/2002",
             "https://openalex.org/subfields/2002",
             "https://api.openalex.org/subfields/2002"]
    keys = {topic_vec.canonical_subfield_id(x) for x in forms}
    assert keys == {"2002"}
    with pytest.raises(ValueError):
        topic_vec.canonical_subfield_id(None)


def test_person_topic_vec_frozen_and_canonical(mk):
    """Person topic vector = subfield count distribution of works up to t-1 (keys already normalized); comparable across formats."""
    edges_a = _pedges([("W1", "P_A", 2014), ("W2", "P_A", 2015), ("W3", "P_A", 2016)])
    works_by_id = {
        "W1": mk.work("W1", 2014, subfield_id="subfields/2002"),
        "W2": mk.work("W2", 2015, subfield_id=2002),
        "W3": mk.work("W3", 2016, subfield_id="2003"),  # Beyond the freeze point
    }
    vec = topic_vec.person_topic_vec("P_A", edges_a, works_by_id, 2015)
    assert vec == {"2002": 2.0}  # Both formats normalize to the same key; the 2016 work does not enter

    # Cosine with another person (URL format) = 1.0 (identical distribution), so it matches even without raw comparison
    edges_b = _pedges([("W9", "P_B", 2014)])
    works_by_id["W9"] = mk.work("W9", 2014,
                                subfield_id="https://openalex.org/subfields/2002")
    vec_b = topic_vec.person_topic_vec("P_B", edges_b, works_by_id, 2015)
    assert topic_vec.pair_topic_cos(vec, vec_b) == pytest.approx(1.0)


def test_topic_vec_goes_through_single_cutoff(monkeypatch, mk):
    """#7 (topic side): person_topic_vec goes through cutoff.filter_works_until (spy)."""
    from m4_dose import cutoff as cutoff_mod

    seen = []
    real = cutoff_mod.filter_works_until

    def spy(rows, t):
        seen.append(t)
        return real(rows, t)

    monkeypatch.setattr(cutoff_mod, "filter_works_until", spy)
    edges = _pedges([("W1", "P_A", 2014)])
    topic_vec.person_topic_vec("P_A", edges, {"W1": mk.work("W1", 2014)}, 2015)
    assert seen == [2015]


# ---------------------------------------------------------------------------
# #22 the primary dose is not mixed with the secondary: source guard (a hard test, never to be downgraded to a comment)
# ---------------------------------------------------------------------------
def test_secondary_not_in_main_dose():
    """#22: the source of the four primary-path modules never touches abstract/embedding/topic/work_text: physical isolation."""
    from m4_dose import candidate_pairs, coupling, cutoff, degree2_closure

    for mod in (cutoff, candidate_pairs, degree2_closure, coupling):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        low = src.lower()
        for token in ("abstract", "embedding", "embed_cos", "topic_cos", "work_text"):
            # A docstring may mention a negated "does not touch X", but to be strictest, ban every mention:
            assert token not in low, (
                f"main dose module {mod.__name__} source contains the secondary-dose root {token!r} — "
                "#22 main/secondary physical separation is broken"
            )
