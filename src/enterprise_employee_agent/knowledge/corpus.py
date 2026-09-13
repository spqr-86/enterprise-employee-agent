"""Frozen corpus manifest loading and deterministic validation.

The v0.1 corpus is a byte-stable subset of the public GitLab Handbook. ``data/manifest.json``
records provenance and a SHA-256 for every imported file. Validation is offline and read-only:
it never fetches, rewrites, or normalizes source text.

Manifest document paths are relative to the source directory (``data/source/`` by default), and
they are also used as stable document IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
DEFAULT_SOURCE_DIR = DATA_DIR / "source"
DEFAULT_MANIFEST_PATH = DATA_DIR / "manifest.json"

_HASH_CHUNK_BYTES = 1 << 20

_REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "corpus_version",
    "source",
    "normalization_version",
    "chunking_version",
    "documents",
)
_REQUIRED_SOURCE_FIELDS = ("repository", "snapshot_revision", "retrieved_at", "licence")
_REQUIRED_DOCUMENT_FIELDS = (
    "id",
    "title",
    "source_path",
    "source_url",
    "path",
    "sha256",
    "bytes",
)


class CorpusError(Exception):
    """Raised when the frozen corpus and its manifest are inconsistent."""


@dataclass(frozen=True)
class CorpusDocument:
    id: str
    title: str
    source_path: str
    source_url: str
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True)
class CorpusManifest:
    schema_version: int
    corpus_version: str
    source: dict[str, str]
    normalization_version: str
    chunking_version: str
    documents: tuple[CorpusDocument, ...]


def sha256_file(path: Path) -> str:
    """Return the lowercase hex SHA-256 of a file's exact bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(mapping: dict[str, Any], field: str, where: str) -> Any:
    if field not in mapping:
        raise CorpusError(f"{where} is missing required field: {field}")
    return mapping[field]


def _require_str(mapping: dict[str, Any], field: str, where: str) -> str:
    value = _require(mapping, field, where)
    if not isinstance(value, str) or not value:
        raise CorpusError(f"{where}.{field} must be a non-empty string")
    return value


def load_manifest(manifest_path: Path = DEFAULT_MANIFEST_PATH) -> CorpusManifest:
    """Load and structurally validate a manifest without touching source files."""
    if not manifest_path.is_file():
        raise CorpusError(f"manifest does not exist: {manifest_path}")

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise CorpusError(f"manifest is not valid JSON: {error}") from error

    if not isinstance(raw, dict):
        raise CorpusError("manifest must be a JSON object")

    schema_version = _require(raw, "schema_version", "manifest")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise CorpusError("manifest.schema_version must be an integer")

    source = _require(raw, "source", "manifest")
    if not isinstance(source, dict):
        raise CorpusError("manifest.source must be an object")
    for field in _REQUIRED_SOURCE_FIELDS:
        _require_str(source, field, "manifest.source")

    documents_raw = _require(raw, "documents", "manifest")
    if not isinstance(documents_raw, list) or not documents_raw:
        raise CorpusError("manifest.documents must be a non-empty array")

    documents: list[CorpusDocument] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, entry in enumerate(documents_raw):
        where = f"manifest.documents[{index}]"
        if not isinstance(entry, dict):
            raise CorpusError(f"{where} must be an object")
        values = {
            field: _require_str(entry, field, where)
            for field in _REQUIRED_DOCUMENT_FIELDS
            if field != "bytes"
        }
        size = _require(entry, "bytes", where)
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise CorpusError(f"{where}.bytes must be a non-negative integer")

        if values["id"] in seen_ids:
            raise CorpusError(f"duplicate document id: {values['id']}")
        if values["path"] in seen_paths:
            raise CorpusError(f"duplicate document path: {values['path']}")
        seen_ids.add(values["id"])
        seen_paths.add(values["path"])

        documents.append(
            CorpusDocument(
                id=values["id"],
                title=values["title"],
                source_path=values["source_path"],
                source_url=values["source_url"],
                path=values["path"],
                sha256=values["sha256"].lower(),
                bytes=size,
            )
        )

    return CorpusManifest(
        schema_version=schema_version,
        corpus_version=_require_str(raw, "corpus_version", "manifest"),
        source={field: str(source[field]) for field in _REQUIRED_SOURCE_FIELDS},
        normalization_version=_require_str(raw, "normalization_version", "manifest"),
        chunking_version=_require_str(raw, "chunking_version", "manifest"),
        documents=tuple(documents),
    )


def _resolve_document_path(source_dir: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise CorpusError(f"unsafe document path: {relative}")
    return source_dir / candidate


def validate_corpus(
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    source_dir: Path = DEFAULT_SOURCE_DIR,
) -> CorpusManifest:
    """Validate the manifest against the exact source tree; raise on any mismatch."""
    manifest = load_manifest(manifest_path)

    if not source_dir.is_dir():
        raise CorpusError(f"source directory does not exist: {source_dir}")

    declared_paths = {document.path for document in manifest.documents}
    for document in manifest.documents:
        target = _resolve_document_path(source_dir, document.path)
        if not target.is_file():
            raise CorpusError(f"source file is missing: {document.path}")
        data = target.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        if actual_hash != document.sha256:
            raise CorpusError(
                f"sha256 mismatch for {document.path}: "
                f"manifest={document.sha256} actual={actual_hash}"
            )
        if len(data) != document.bytes:
            raise CorpusError(
                f"bytes mismatch for {document.path}: manifest={document.bytes} actual={len(data)}"
            )

    discovered = {
        path.relative_to(source_dir).as_posix() for path in source_dir.rglob("*") if path.is_file()
    }
    undeclared = sorted(discovered - declared_paths)
    if undeclared:
        raise CorpusError("source file is not declared in the manifest: " + ", ".join(undeclared))
    missing = sorted(declared_paths - discovered)
    if missing:
        raise CorpusError("declared source file is missing: " + ", ".join(missing))

    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the frozen corpus; print a summary and return a process exit code."""
    parser = argparse.ArgumentParser(description="Validate the frozen corpus manifest.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    args = parser.parse_args(argv)

    try:
        manifest = validate_corpus(args.manifest, args.source_dir)
    except CorpusError as error:
        print(f"corpus check failed: {error}", file=sys.stderr)
        return 1

    print(
        f"corpus OK: {len(manifest.documents)} documents, "
        f"version {manifest.corpus_version}, normalisation {manifest.normalization_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
