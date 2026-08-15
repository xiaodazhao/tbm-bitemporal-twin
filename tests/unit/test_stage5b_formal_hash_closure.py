"""Stage 5B formal artifact hash-closure tests."""

from __future__ import annotations

import hashlib

from tests.unit.stage5b_helpers import stage5b_formal_artifact


def test_stage5b_formal_hash_closure(tmp_path_factory) -> None:
    artifact = stage5b_formal_artifact(tmp_path_factory)
    hash_file = artifact / "file_hashes.sha256"
    rows = [line.split(maxsplit=1) for line in hash_file.read_text(encoding="utf-8").splitlines()]

    assert rows
    for expected, rel_path in rows:
        path = artifact / rel_path.lstrip("*")
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
