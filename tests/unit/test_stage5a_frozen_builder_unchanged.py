"""Stage 5B boundary test for the authoritative frozen Stage 5A artifact."""

from __future__ import annotations

import hashlib
from pathlib import Path


def test_stage5a_frozen_artifact_matches_its_hash_manifest() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    artifact = repo_root / "artifacts/stage5a_typed_claim_contract_v1_1"
    manifest = artifact / "file_hashes.sha256"

    assert manifest.is_file()
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(maxsplit=1)
        path = artifact / relative
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, relative
