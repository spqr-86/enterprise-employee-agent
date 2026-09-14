"""Versioned document access map: which role may read which knowledge document.

Handbook documents come from the frozen corpus (``data/manifest.json``) and are validated by
``corpus.validate_corpus``. Synthetic restricted fixtures live next to the access map under
``data/synthetic_protected/`` and are validated here the same way: path safety, exact bytes,
SHA-256 and size. The map is demonstration data; it does not prove production access control.
"""

# ANCHOR: Loads the versioned document access map, validates the frozen corpus and synthetic
# fixture bytes against it, and exposes readable_by(role) for the retrieval pipeline (Task 2).

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from enterprise_employee_agent.knowledge.corpus import (
    DATA_DIR,
    DEFAULT_MANIFEST_PATH,
    DEFAULT_SOURCE_DIR,
    validate_corpus,
)
from enterprise_employee_agent.leave.contracts import ActorRole, ContractModel

DEFAULT_ACCESS_PATH = DATA_DIR / "synthetic_protected" / "document-access-v1.json"
SYNTHETIC_ID_PREFIX = "synthetic/"
RESTRICTED_FIXTURE_ID = "synthetic/hr-only-note"


class DocumentAccessError(Exception):
    """Raised when the access map, its synthetic fixtures, and the corpus disagree."""


class DocumentVisibility(StrEnum):
    PUBLIC = "public"
    HR_ONLY = "hr_only"


VISIBILITY_ROLES: dict[DocumentVisibility, frozenset[ActorRole]] = {
    DocumentVisibility.PUBLIC: frozenset(ActorRole),
    DocumentVisibility.HR_ONLY: frozenset({ActorRole.HR}),
}


class _AccessEntry(ContractModel):
    id: str = Field(min_length=1)
    visibility: DocumentVisibility
    path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    bytes: int | None = Field(default=None, ge=0)


class _AccessFile(ContractModel):
    schema_version: Literal[1]
    access_version: str = Field(min_length=1)
    corpus_version: str = Field(min_length=1)
    documents: tuple[_AccessEntry, ...]


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    id: str
    text: str
    visibility: DocumentVisibility


@dataclass(frozen=True, slots=True)
class DocumentAccessMap:
    access_version: str
    corpus_version: str
    documents: tuple[KnowledgeDocument, ...]

    def readable_by(self, role: ActorRole) -> tuple[KnowledgeDocument, ...]:
        return tuple(
            document for document in self.documents if role in VISIBILITY_ROLES[document.visibility]
        )


def _safe_relative(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise DocumentAccessError(f"unsafe fixture path: {path}")
    return candidate


def _read_synthetic(access_path: Path, entry: _AccessEntry) -> str:
    if entry.path is None or entry.sha256 is None or entry.bytes is None:
        raise DocumentAccessError(f"synthetic document {entry.id} requires path, sha256 and bytes")
    target = access_path.parent / _safe_relative(entry.path)
    if not target.is_file():
        raise DocumentAccessError(f"synthetic fixture is missing: {entry.path}")
    data = target.read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != entry.sha256:
        raise DocumentAccessError(
            f"sha256 mismatch for {entry.path}: map={entry.sha256} actual={actual}"
        )
    if len(data) != entry.bytes:
        raise DocumentAccessError(
            f"bytes mismatch for {entry.path}: map={entry.bytes} actual={len(data)}"
        )
    return data.decode("utf-8")


def load_document_access_map(
    access_path: Path = DEFAULT_ACCESS_PATH,
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    source_dir: Path = DEFAULT_SOURCE_DIR,
) -> DocumentAccessMap:
    """Load the access map, validating the corpus and every synthetic fixture."""
    manifest = validate_corpus(manifest_path, source_dir)
    try:
        raw = _AccessFile.model_validate_json(access_path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise DocumentAccessError(f"invalid document access map {access_path}: {error}") from error

    if raw.corpus_version != manifest.corpus_version:
        raise DocumentAccessError(
            f"access map corpus_version {raw.corpus_version!r} does not match manifest "
            f"{manifest.corpus_version!r}"
        )

    handbook = {document.id: document for document in manifest.documents}
    seen: set[str] = set()
    documents: list[KnowledgeDocument] = []
    for entry in raw.documents:
        if entry.id in seen:
            raise DocumentAccessError(f"duplicate document id in access map: {entry.id}")
        seen.add(entry.id)
        if entry.id in handbook:
            if entry.path is not None or entry.sha256 is not None or entry.bytes is not None:
                raise DocumentAccessError(
                    f"handbook document {entry.id} must not declare fixture fields"
                )
            text = (source_dir / handbook[entry.id].path).read_text(encoding="utf-8")
        elif entry.id.startswith(SYNTHETIC_ID_PREFIX):
            text = _read_synthetic(access_path, entry)
        else:
            raise DocumentAccessError(f"unknown document id in access map: {entry.id}")
        documents.append(KnowledgeDocument(id=entry.id, text=text, visibility=entry.visibility))

    unlisted = sorted(set(handbook) - seen)
    if unlisted:
        raise DocumentAccessError(
            "handbook documents missing from access map: " + ", ".join(unlisted)
        )

    return DocumentAccessMap(
        access_version=raw.access_version,
        corpus_version=raw.corpus_version,
        documents=tuple(documents),
    )
