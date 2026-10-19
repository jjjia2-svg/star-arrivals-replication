"""U0 common/manifest.py: Merkle/SHA freeze credential + merged_ids replay + provenance shape.

Follows build checklist C.9 + G group 7 (appendix E):
  - merkle_root: order sensitive (reordering changes the root) = the dataset freeze credential.
  - sha256_file: file-level SHA256.
  - write_dataset_commit / dataset_is_valid: two-phase COMMIT; a dataset that has not reached COMMIT is judged invalid
    (atomic-commit semantics, so a dirty directory left by a crash between the two phases is never taken as valid).
  - replay_merged_ids: iteratively find the root (follow the raw->canonical pointer chain to its root), raise on a cycle,
    return {raw_id: (canonical_id, is_deleted)}; is_deleted = whether the endpoint is a deletion sentinel.
  - provenance comparison: the 4-tuple PROVENANCE_KEYS compared as strings; any inequality -> raise ProvenanceMismatch (=13)
    HALT (not WARN, HIGH-7). Only the source_snapshot_merkle already stored in the artifact header is compared for equality; merkle is never recomputed.
  - rule_version containing "unsigned" -> the artifact goes to staging, not _frozen/, and the header has rule_version_signed=False (unsigned-rule isolation).

Iron rules:
  - The exit code is identity.exit_codes.PROVENANCE_MISMATCH (single source of truth P-5); this module invents no bare number.
  - DELETION_SENTINELS_AUTHORS is an empty-set placeholder, to be filled from the m0 measurement (I.2[q]); no value is filled in here.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from typing import Any, Iterable, Mapping

# G7 atomic write (with durable fsync): the two-phase COMMIT write goes through it, adding durability (a crash leaves no half file).
from common.atomic_io import atomic_write_bytes
# Single source of truth for exit codes (P-5): the HALT code for a provenance mismatch comes from the identity layer; this module does not invent it.
# src/ is already put on sys.path by the tests / callers; imports are within the same package level.
from identity import exit_codes

# ===========================================================================
# Constants (C.9)
# ===========================================================================

# Provenance 4-tuple: recorded in the artifact header; the only key set for comparing frozen copies across units (appendix E).
PROVENANCE_KEYS: tuple[str, str, str, str] = (
    "source_snapshot_merkle",
    "config_sha",
    "rule_version",
    "stars_set_hash",
)

# Deletion sentinels: resolving to one of these canonical ids gives is_deleted=True.
# WORKS is known to include the OpenAlex merge-deletion target W4285719527 (pinned in C.9).
DELETION_SENTINELS_WORKS: set[str] = {"W4285719527"}
# AUTHORS: empty-set placeholder, to be filled from the m0 measurement (I.2[q]); no value is filled in here.
DELETION_SENTINELS_AUTHORS: set[str] = set()

# COMMIT marker file name + artifact header file name.
_COMMIT_MARKER = "COMMIT"
_HEADER_NAME = "manifest_header.json"
_STAGING_SUBDIR = "_staging"
_FROZEN_SUBDIR = "_frozen"


# ===========================================================================
# Exceptions
# ===========================================================================
class ProvenanceMismatch(Exception):
    """Any inequality in the provenance 4-tuple -> HALT (not WARN, HIGH-7).

    Carries exit_code = identity.exit_codes.PROVENANCE_MISMATCH (=13),
    so the caller exits with the shared exit code rather than a bare number.
    """

    exit_code: int = exit_codes.PROVENANCE_MISMATCH

    def __init__(self, message: str, *, key: str | None = None) -> None:
        super().__init__(message)
        self.key = key


# ===========================================================================
# Merkle / SHA (appendix E: freeze credential)
# ===========================================================================
def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def merkle_root(leaves: Iterable[bytes]) -> str:
    """Order-sensitive Merkle root (reordering changes the root): the dataset freeze credential (T21).

    Construction = a binary Merkle tree over the ordered leaves, with domain separation:
      - leaf: H(0x00 || leaf)  (leaves and inner nodes get different prefixes, against second-preimage attacks).
      - inner node: H(0x01 || left || right).
      - odd number of nodes -> the last node is paired with itself (Bitcoin style).
    Order sensitivity comes from the pairing structure: swapping two adjacent leaves changes the parent hash and so the root.
    Empty leaf set -> H(0x02) (a deterministic sentinel different from the single-leaf and multi-leaf cases; does not crash).
    """
    leaf_list = list(leaves)
    if not leaf_list:
        return _sha256_hex(b"\x02")  # Dedicated sentinel root for the empty set
    # Leaf level
    level: list[bytes] = [
        hashlib.sha256(b"\x00" + leaf).digest() for leaf in leaf_list
    ]
    # Go up level by level until one root is left
    while len(level) > 1:
        nxt: list[bytes] = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else level[i]  # Odd count: pad with itself
            nxt.append(hashlib.sha256(b"\x01" + left + right).digest())
        level = nxt
    return level[0].hex()


def sha256_file(path: pathlib.Path | str) -> str:
    """SHA256 hex of the file content (read in chunks, never loading the whole file into memory)."""
    p = pathlib.Path(path)
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ===========================================================================
# merged_ids replay (appendix E: iterative root finding + cycle detection + is_deleted)
# ===========================================================================
def replay_merged_ids(
    rows: Iterable[Mapping[str, Any]],
    *,
    deletion_sentinels: set[str],
) -> dict[str, tuple[str, bool]]:
    """Replay the raw->canonical merge chain, finding roots iteratively (T23).

    Input rows: each = {"raw_id": str, "canonical_id": str} (a subset of CANONICAL_ID_MAP).
    Returns: {raw_id: (terminal_canonical_id, is_deleted)}.
      - terminal_canonical_id = the root reached by following the pointer chain until nothing redirects it any more.
      - is_deleted = whether that root is in deletion_sentinels.
    A cycle (raw->...->raw) -> raise ValueError (never loops forever).

    Iron rule: roots are found iteratively (not recursively); each resolution uses its own visited set for cycle detection.
    """
    # Build the raw->canonical pointer table (a later row overrides an earlier one = the last write wins in an append-only log).
    redirect: dict[str, str] = {}
    for row in rows:
        raw = row["raw_id"]
        canon = row["canonical_id"]
        redirect[raw] = canon

    out: dict[str, tuple[str, bool]] = {}
    for start in redirect:
        cur = start
        visited: set[str] = set()
        # Follow the chain: while cur is still the source of some redirect, keep jumping.
        while cur in redirect:
            if cur in visited:
                raise ValueError(
                    f"replay_merged_ids found a merge cycle: starting from {start!r} it loops at {cur!r}"
                )
            visited.add(cur)
            cur = redirect[cur]
        is_deleted = cur in deletion_sentinels
        out[start] = (cur, is_deleted)
    return out


# ===========================================================================
# provenance comparison (appendix E: 4-tuple equality, merkle not recomputed)
# ===========================================================================
def verify_provenance(
    artifact_header: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    """Compare the provenance 4-tuple PROVENANCE_KEYS; any inequality -> raise ProvenanceMismatch (T24/T25).

    Only the strings already stored on the two sides are compared for equality; merkle_root is never called to recompute (HIGH-7).
      source_snapshot_merkle is, on both sides, the existing value written into the artifact header when m0 was frozen.
    All equal -> returns True (no raise).
    A missing key -> treated as unequal (the KeyError path also counts as a mismatch, never let through silently).
    """
    for key in PROVENANCE_KEYS:
        got = artifact_header.get(key, _MISSING)
        want = expected.get(key, _MISSING)
        if got != want or got is _MISSING:
            raise ProvenanceMismatch(
                f"provenance does not equal {key!r}: artifact header={got!r} expected={want!r} — HALT (not WARN)",
                key=key,
            )
    return True


_MISSING = object()


# ===========================================================================
# Two-phase COMMIT (appendix E: atomic commit + unsigned-rule isolation)
# ===========================================================================
def _rule_version_signed(rule_version: str) -> bool:
    """rule_version containing 'unsigned' -> unsigned (goes to staging); otherwise signed (may go to _frozen)."""
    return "unsigned" not in str(rule_version).lower()


class _DatasetCommitter:
    """Two-phase COMMIT writer (T22/T26).

    Phase 1 stage(): data + artifact header go to the staging area (_staging/); no COMMIT is written.
    Phase 2 commit(): write the COMMIT marker;
       - signed rule_version -> promote the staging content to _frozen/ (including COMMIT); only then is the dataset valid.
       - contains unsigned -> COMMIT goes only to staging, never to _frozen/ (unsigned-rule isolation).
    dataset_is_valid(root) accepts only _frozen/COMMIT, so an unsigned artifact is always judged invalid.
    """

    def __init__(
        self,
        root: pathlib.Path,
        payload: Mapping[str, bytes],
        *,
        provenance: Mapping[str, Any],
    ) -> None:
        self.root = pathlib.Path(root)
        self.payload = dict(payload)
        self.provenance = dict(provenance)
        rv = self.provenance.get("rule_version", "")
        self._signed = _rule_version_signed(rv)
        self.staging_dir = self.root / _STAGING_SUBDIR
        self.frozen_dir = self.root / _FROZEN_SUBDIR
        # Artifact header: provenance 4-tuple + signed flag + data merkle (freeze credential).
        leaves = [self.payload[name] for name in sorted(self.payload)]
        self.header: dict[str, Any] = {
            **{k: self.provenance.get(k) for k in PROVENANCE_KEYS},
            "rule_version_signed": self._signed,
            "dataset_merkle": merkle_root(leaves),
        }
        self._staged = False
        self._committed = False

    def stage(self) -> "_DatasetCommitter":
        """Phase 1: data + header go to staging; no COMMIT is written (dataset_is_valid=False at this point).

        Writing goes through atomic_write_bytes (G7 + durable fsync): every payload file and the artifact header are
        really flushed to disk, and a crash leaves no half file (adversarial QA: the original write_bytes/write_text had no fsync = a durability gap).
        The two-phase semantics are unchanged: only data/header are written here, no COMMIT -> the dataset is still judged invalid.
        """
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        for name, data in self.payload.items():
            atomic_write_bytes(self.staging_dir / name, data)
        atomic_write_bytes(
            self.staging_dir / _HEADER_NAME,
            json.dumps(self.header, sort_keys=True, ensure_ascii=False).encode("utf-8"),
        )
        self._staged = True
        return self

    def commit(self) -> "_DatasetCommitter":
        """Phase 2: write COMMIT; if signed, promote to _frozen/, if unsigned keep it in staging.

        Writing goes through atomic_write_bytes (G7 + durable fsync): the COMMIT marker and the promoted data/header are
        really flushed to disk. The two-phase atomic semantics are unchanged: the COMMIT marker is the last step of validity, and the atomic write ensures
        it is either fully present or absent (a crash midway never leaves a half COMMIT that makes a dirty dataset look valid).
        """
        if not self._staged:
            raise RuntimeError("stage() must be called before commit()")
        # Write COMMIT in the staging area first (signed or not, staging stays self-consistent).
        atomic_write_bytes(self.staging_dir / _COMMIT_MARKER, b"ok")
        if self._signed:
            # Signed -> promote: copy data + header + COMMIT to _frozen/.
            self.frozen_dir.mkdir(parents=True, exist_ok=True)
            for name, data in self.payload.items():
                atomic_write_bytes(self.frozen_dir / name, data)
            atomic_write_bytes(
                self.frozen_dir / _HEADER_NAME,
                json.dumps(self.header, sort_keys=True, ensure_ascii=False).encode("utf-8"),
            )
            atomic_write_bytes(self.frozen_dir / _COMMIT_MARKER, b"ok")
        # Contains unsigned: never create _frozen/ (unsigned-rule isolation) -> the dataset stays invalid until the rule version is signed.
        self._committed = True
        return self


def write_dataset_commit(
    root: pathlib.Path | str,
    payload: Mapping[str, bytes],
    *,
    provenance: Mapping[str, Any],
) -> _DatasetCommitter:
    """Create a two-phase COMMIT writer (nothing is written yet). The caller runs .stage() and then .commit().

    The two phases exist for atomicity: a crash between stage and commit -> the directory has data but no _frozen/COMMIT
    -> dataset_is_valid=False, so downstream never mistakes it for valid.
    """
    return _DatasetCommitter(pathlib.Path(root), payload, provenance=provenance)


def dataset_is_valid(root: pathlib.Path | str) -> bool:
    """Whether the dataset is valid = the _frozen/COMMIT marker is present (T22).

    Not yet at COMMIT / only staged without commit / contains unsigned and was not promoted -> no _frozen/COMMIT -> False.
    Only the COMMIT of the frozen copy counts, so a dirty directory left midway through the two phases is always judged invalid.
    """
    frozen_commit = pathlib.Path(root) / _FROZEN_SUBDIR / _COMMIT_MARKER
    return frozen_commit.is_file()
