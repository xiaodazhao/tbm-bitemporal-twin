"""I/O helpers for Stage 3B."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tbm_twin.state.io import read_json, read_jsonl, sha256_file


def load_stage3a_inputs(stage3a_dir: Path) -> dict[str, Any]:
    """Load formal Stage 3A artifacts."""

    return {
        "manifest": read_json(stage3a_dir / "freeze_manifest.json"),
        "method_version": read_json(stage3a_dir / "method_version.json"),
        "cells": read_jsonl(stage3a_dir / "construction_state_cells.jsonl"),
        "daily_states": read_jsonl(stage3a_dir / "daily_construction_states.jsonl"),
        "state_versions": read_jsonl(stage3a_dir / "initial_construction_state_versions.jsonl"),
        "geological_links": read_jsonl(stage3a_dir / "state_geological_evidence_links.jsonl"),
        "response_links": read_jsonl(stage3a_dir / "state_response_evidence_links.jsonl"),
        "assertion_trace_links": read_jsonl(stage3a_dir / "state_assertion_trace_links.jsonl"),
        "unlocated_clause_traces": read_jsonl(stage3a_dir / "daily_unlocated_clause_trace.jsonl"),
        "file_hash_manifest_hash": sha256_file(stage3a_dir / "file_hashes.sha256"),
    }


def load_geology_inputs(geology_dir: Path) -> dict[str, Any]:
    """Load formal Stage 2 geology freeze artifacts."""

    return {
        "manifest": read_json(geology_dir / "freeze_manifest.json"),
        "documents": read_jsonl(geology_dir / "geological_documents.jsonl"),
        "evidence": read_jsonl(geology_dir / "primary_geological_evidence.jsonl"),
        "source_spans": read_jsonl(geology_dir / "source_spans.jsonl"),
        "report_assertions": read_jsonl(geology_dir / "report_assertions.jsonl"),
        "unlocated_clauses": read_jsonl(geology_dir / "unlocated_clauses.jsonl"),
    }
