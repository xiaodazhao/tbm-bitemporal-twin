"""Hash helpers for source assets."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def stable_asset_id(source_type: str, content_hash: str, schema_version: str) -> str:
    """Generate a reproducible asset id from immutable source properties."""

    seed = f"{source_type}:{schema_version}:{content_hash}".encode()
    suffix = hashlib.sha256(seed).hexdigest()[:20]
    return f"{source_type.lower()}-{suffix}"
