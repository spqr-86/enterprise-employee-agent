from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enterprise_employee_agent.knowledge.access import (
    RESTRICTED_FIXTURE_ID,
    DocumentAccessError,
    DocumentVisibility,
    load_document_access_map,
)
from enterprise_employee_agent.knowledge.corpus import load_manifest
from enterprise_employee_agent.leave.contracts import ActorRole

HANDBOOK_IDS = (
    "people-policies/leave-of-absence/_index.md",
    "people-policies/leave-of-absence/us.md",
)
NOTE = "# Synthetic\n\nRestricted text.\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _synthetic_entry(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "id": "synthetic/note",
        "visibility": "hr_only",
        "path": "documents/note.md",
        "sha256": _sha(NOTE),
        "bytes": len(NOTE.encode("utf-8")),
    }
    entry.update(overrides)
    return entry


def _write_map(
    tmp_path: Path,
    *,
    documents: list[dict[str, object]] | None = None,
    corpus_version: str | None = None,
) -> Path:
    fixture = tmp_path / "documents" / "note.md"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_bytes(NOTE.encode("utf-8"))
    entries = (
        documents
        if documents is not None
        else [
            *({"id": document_id, "visibility": "public"} for document_id in HANDBOOK_IDS),
            _synthetic_entry(),
        ]
    )
    payload = {
        "schema_version": 1,
        "access_version": "test-access",
        "corpus_version": corpus_version or load_manifest().corpus_version,
        "documents": entries,
    }
    path = tmp_path / "access.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_repository_access_map_loads_all_documents() -> None:
    access_map = load_document_access_map()
    assert access_map.access_version == "document-access-v1"
    assert access_map.corpus_version == load_manifest().corpus_version
    assert {document.id for document in access_map.documents} == {
        *HANDBOOK_IDS,
        RESTRICTED_FIXTURE_ID,
    }


def test_restricted_fixture_is_readable_only_by_hr() -> None:
    access_map = load_document_access_map()
    restricted = next(d for d in access_map.documents if d.id == RESTRICTED_FIXTURE_ID)
    assert restricted.visibility is DocumentVisibility.HR_ONLY
    assert "SYNTHETIC FIXTURE" in restricted.text
    for role in (ActorRole.EMPLOYEE, ActorRole.MANAGER):
        assert RESTRICTED_FIXTURE_ID not in {d.id for d in access_map.readable_by(role)}
    assert RESTRICTED_FIXTURE_ID in {d.id for d in access_map.readable_by(ActorRole.HR)}


def test_employee_reads_both_handbook_documents() -> None:
    readable = load_document_access_map().readable_by(ActorRole.EMPLOYEE)
    assert {document.id for document in readable} == set(HANDBOOK_IDS)


def test_valid_temporary_map_loads(tmp_path: Path) -> None:
    access_map = load_document_access_map(_write_map(tmp_path))
    assert "synthetic/note" in {document.id for document in access_map.documents}


def test_fixture_hash_mismatch_fails(tmp_path: Path) -> None:
    documents = [
        *({"id": d, "visibility": "public"} for d in HANDBOOK_IDS),
        _synthetic_entry(sha256="0" * 64),
    ]
    with pytest.raises(DocumentAccessError, match="sha256"):
        load_document_access_map(_write_map(tmp_path, documents=documents))


def test_fixture_byte_size_mismatch_fails(tmp_path: Path) -> None:
    documents = [
        *({"id": d, "visibility": "public"} for d in HANDBOOK_IDS),
        _synthetic_entry(bytes=1),
    ]
    with pytest.raises(DocumentAccessError, match="bytes"):
        load_document_access_map(_write_map(tmp_path, documents=documents))


def test_unknown_document_id_is_rejected(tmp_path: Path) -> None:
    documents = [
        *({"id": d, "visibility": "public"} for d in HANDBOOK_IDS),
        {"id": "people-policies/leave-of-absence/de.md", "visibility": "public"},
    ]
    with pytest.raises(DocumentAccessError, match="unknown document id"):
        load_document_access_map(_write_map(tmp_path, documents=documents))


def test_handbook_document_missing_from_map_is_rejected(tmp_path: Path) -> None:
    documents = [{"id": HANDBOOK_IDS[0], "visibility": "public"}, _synthetic_entry()]
    with pytest.raises(DocumentAccessError, match="missing from access map"):
        load_document_access_map(_write_map(tmp_path, documents=documents))


def test_duplicate_document_id_is_rejected(tmp_path: Path) -> None:
    documents = [
        *({"id": d, "visibility": "public"} for d in HANDBOOK_IDS),
        {"id": HANDBOOK_IDS[0], "visibility": "hr_only"},
    ]
    with pytest.raises(DocumentAccessError, match="duplicate"):
        load_document_access_map(_write_map(tmp_path, documents=documents))


def test_corpus_version_mismatch_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DocumentAccessError, match="corpus_version"):
        load_document_access_map(_write_map(tmp_path, corpus_version="other-corpus"))


def test_unsafe_fixture_path_is_rejected(tmp_path: Path) -> None:
    documents = [
        *({"id": d, "visibility": "public"} for d in HANDBOOK_IDS),
        _synthetic_entry(path="../outside.md"),
    ]
    with pytest.raises(DocumentAccessError, match="unsafe"):
        load_document_access_map(_write_map(tmp_path, documents=documents))


def test_synthetic_entry_without_hash_is_rejected(tmp_path: Path) -> None:
    documents = [
        *({"id": d, "visibility": "public"} for d in HANDBOOK_IDS),
        {"id": "synthetic/note", "visibility": "hr_only", "path": "documents/note.md"},
    ]
    with pytest.raises(DocumentAccessError, match="requires path, sha256 and bytes"):
        load_document_access_map(_write_map(tmp_path, documents=documents))
