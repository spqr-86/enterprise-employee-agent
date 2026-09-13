from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from enterprise_employee_agent.knowledge import corpus

DOC_TEXT = "# United States Leave of Absence\n\nFrozen body.\n"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "id": "us-leave",
        "title": "United States Leave of Absence Policies",
        "source_path": "people-policies/leave-of-absence/us.md",
        "source_url": "https://handbook.gitlab.com/handbook/people-policies/leave-of-absence/us/",
        "path": "people-policies/leave-of-absence/us.md",
        "sha256": _sha256(DOC_TEXT),
        "bytes": len(DOC_TEXT.encode("utf-8")),
    }
    document.update(overrides)
    return document


def _manifest(*documents: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "corpus_version": "test-2026-09-12",
        "source": {
            "repository": "https://gitlab.com/gitlab-com/content-sites/handbook.git",
            "snapshot_revision": "f7b8be0fca997b7f7571a0f63ca1ac75420e4bb6",
            "retrieved_at": "2026-07-03T16:48:48Z",
            "licence": "MIT",
        },
        "normalization_version": "raw-v1",
        "chunking_version": "none-v1",
        "documents": list(documents) if documents else [_document()],
    }


def _build_corpus(
    tmp_path: Path, manifest: dict[str, object], *, write_docs: bool = True
) -> tuple[Path, Path]:
    source_dir = tmp_path / "source"
    if write_docs:
        for document in manifest["documents"]:  # type: ignore[union-attr]
            target = source_dir / str(document["path"])  # type: ignore[index]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(DOC_TEXT, encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path, source_dir


def test_valid_corpus_returns_documents(tmp_path: Path) -> None:
    manifest_path, source_dir = _build_corpus(tmp_path, _manifest())

    manifest = corpus.validate_corpus(manifest_path, source_dir)

    assert manifest.schema_version == 1
    assert [document.id for document in manifest.documents] == ["us-leave"]


def test_missing_source_file_fails(tmp_path: Path) -> None:
    manifest_path, source_dir = _build_corpus(tmp_path, _manifest(), write_docs=False)

    with pytest.raises(corpus.CorpusError, match="missing"):
        corpus.validate_corpus(manifest_path, source_dir)


def test_extra_source_file_fails(tmp_path: Path) -> None:
    manifest_path, source_dir = _build_corpus(tmp_path, _manifest())
    extra = source_dir / "people-policies" / "leave-of-absence" / "extra.md"
    extra.write_text("stray\n", encoding="utf-8")

    with pytest.raises(corpus.CorpusError, match="not declared"):
        corpus.validate_corpus(manifest_path, source_dir)


def test_hash_mismatch_fails(tmp_path: Path) -> None:
    manifest_path, source_dir = _build_corpus(tmp_path, _manifest(_document(sha256="0" * 64)))

    with pytest.raises(corpus.CorpusError, match="sha256"):
        corpus.validate_corpus(manifest_path, source_dir)


def test_byte_size_mismatch_fails(tmp_path: Path) -> None:
    manifest_path, source_dir = _build_corpus(tmp_path, _manifest(_document(bytes=1)))

    with pytest.raises(corpus.CorpusError, match="bytes"):
        corpus.validate_corpus(manifest_path, source_dir)


def test_duplicate_document_ids_fail(tmp_path: Path) -> None:
    duplicate = _document(path="people-policies/leave-of-absence/other.md")
    manifest_path, source_dir = _build_corpus(tmp_path, _manifest(_document(), duplicate))

    with pytest.raises(corpus.CorpusError, match="duplicate"):
        corpus.validate_corpus(manifest_path, source_dir)


def test_untrusted_path_traversal_is_rejected(tmp_path: Path) -> None:
    manifest_path, source_dir = _build_corpus(
        tmp_path, _manifest(_document(path="../outside.md", id="escape"))
    )

    with pytest.raises(corpus.CorpusError, match="unsafe"):
        corpus.validate_corpus(manifest_path, source_dir)


def test_repository_corpus_matches_manifest() -> None:
    manifest = corpus.validate_corpus()

    assert manifest.corpus_version
    assert {document.id for document in manifest.documents} == {
        "people-policies/leave-of-absence/_index.md",
        "people-policies/leave-of-absence/us.md",
    }
