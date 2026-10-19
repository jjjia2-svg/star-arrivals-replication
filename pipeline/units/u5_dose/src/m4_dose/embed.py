"""m4_dose/embed.py — secondary dose, abstract-embedding channel (#16).

Position: **the secondary dose is only a robustness check and never enters the main dose coupling_share** (#16; #22 main
and secondary are physically separated — main-path modules must never import this file). The embed_cos column is
boundary_sensitive and is not part of the deterministic hash commitment (same note in the identity.embed_cos docstring).

Input contract (#20, B-ABS/B-WT-TITLE resolved):
  work_text = the three U0 / U1 v2 columns {work_id, title, abstract_text} — assert_matches_schema row by row
  (the old has_abstract version or a missing column is rejected); a missing abstract_text value raises.

Determinism / reproducibility (#21):
  - the embedder is an injected deterministic callable (text -> vector); the real model (embed_model_name /
    embed_seed / embed_batch_size, injected parameters) is bound in the run orchestration layer —
    this module only guarantees the machinery "same embedder, same text -> same vector -> byte-identical frozen parquet".
  - the frozen product work_embeddings.parquet is a first-class artefact (canonical-sort by work_id);
    a reproduction reads the frozen vectors, and a model_sha mismatch raises EmbeddingModelMismatch (HALT, never silently recomputed).
  - text_sha = sha256 of the embedded text (audits which source text a frozen vector belongs to).
"""
from __future__ import annotations

import hashlib
import math

from common.schema import WORK_TEXT, assert_matches_schema
from m1_ingest._writer_util import write_rows_parquet

from . import cutoff

# Frozen vector table schema (a first-class frozen U5 product, a local literal; not a U0 registry table).
WORK_EMBEDDINGS: dict[str, str] = {
    "work_id": "str",
    "embedding": "list<float32>",
    "text_sha": "str",
    "model_sha": "str",
}

# Which fields to embed by default (embed_text_fields defaults to ("abstract_text",);
# the title channel is optional: pass the WORK_TEXT schema check before enabling it).
DEFAULT_TEXT_FIELDS: tuple = ("abstract_text",)


class EmbeddingModelMismatch(RuntimeError):
    """The model_sha of the frozen vectors does not match the expected one — reproduction is broken, HALT."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def embed_works(work_text_rows, *, embedder, model_sha: str,
                text_fields: tuple = DEFAULT_TEXT_FIELDS) -> list:
    """Compute sentence vectors for work_text rows -> frozen rows (ascending by work_id, deterministic).

    embedder: deterministic callable(text)->vector (the real model is bound by the run layer from config).
    Every row passes assert_matches_schema(WORK_TEXT) on entry (#20); abstract_text=None -> ValueError.
    """
    out = []
    for row in sorted(work_text_rows, key=lambda r: str(r.get("work_id"))):
        assert_matches_schema(row.keys(), WORK_TEXT, label="work_text")
        parts = []
        for f in text_fields:
            val = row[f]
            if val is None:
                raise ValueError(
                    f"embed_works: work {row['work_id']!r} field {f!r} is None — "
                    "a missing input for the secondary dose is not silently filled with empty text (abstract inversion is done in U1)"
                )
            parts.append(str(val))
        text = "\n\n".join(parts)
        vec = [float(x) for x in embedder(text)]
        out.append({
            "work_id": row["work_id"],
            "embedding": vec,
            "text_sha": _sha256_text(text),
            "model_sha": model_sha,
        })
    return out


def write_frozen_embeddings(rows, target) -> None:
    """Write work_embeddings.parquet frozen (canonical-sort by work_id, deterministic write parameters)."""
    write_rows_parquet(rows, target, schema=WORK_EMBEDDINGS,
                       pk_cols=("work_id",), label="work_embeddings")


def load_frozen_embeddings(path, *, expected_model_sha: str) -> dict:
    """Read frozen vectors -> {work_id: vector}; any row with model_sha != expected -> HALT (#21)."""
    import pyarrow.parquet as pq

    table = pq.read_table(str(path))
    assert_matches_schema(table.column_names, WORK_EMBEDDINGS,
                          label="work_embeddings")
    out: dict = {}
    for row in table.to_pylist():
        if row["model_sha"] != expected_model_sha:
            raise EmbeddingModelMismatch(
                f"work_embeddings: work {row['work_id']!r} model_sha="
                f"{row['model_sha']!r} ≠ expected {expected_model_sha!r} — "
                "the frozen vectors do not match the current model version, HALT (never silently recomputed)"
            )
        out[row["work_id"]] = row["embedding"]
    return out


def person_embed_vec(person_id: str, person_edges, emb_by_work: dict,
                     t_minus_1: int):
    """Person-level secondary dose vector = per-dimension mean of that person's work vectors up to t-1 (fsum, deterministic).

    Truncation goes through cutoff.filter_works_until (#7); if no work with a vector falls within t-1, returns None
    (the calling layer records embed_cos as 0.0 for pairs with None — identity.embed_cos does not accept None).
    """
    frozen = cutoff.filter_works_until(person_edges, t_minus_1)
    work_ids = sorted({
        r["work_id"] for r in frozen if r["person_id"] == person_id
    })
    vecs = [emb_by_work[w] for w in work_ids if w in emb_by_work]
    if not vecs:
        return None
    dim = len(vecs[0])
    n = len(vecs)
    return [math.fsum(v[i] for v in vecs) / n for i in range(dim)]
