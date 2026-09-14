"""Simplest lexical retrieval baseline (Issue #8): role filter first, then token overlap.

Tokenization is lowercase Unicode ``\\w+`` with no stopwords or stemming. The score is the size
of the intersection of question and document token sets. Ties break by document ID ascending,
so results are deterministic. Documents with zero overlap are never returned.
"""

# ANCHOR: Role-filtered lexical retrieval for Issue #8. Input: a question string, the caller's
# ActorRole, and a DocumentAccessMap (Task 1). Output: RetrievedDocument tuples ordered by
# descending overlap score, filtered to documents the role may read before scoring runs.
# rank_documents() is the unfiltered primitive used directly by tests and the forbidden-document
# control; retrieve() is the authorized entry point consumed by later tasks (answer pipeline,
# offline eval).

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from enterprise_employee_agent.knowledge.access import DocumentAccessMap, KnowledgeDocument
from enterprise_employee_agent.leave.contracts import ActorRole

RETRIEVAL_VERSION = "lexical-overlap-v1"
DEFAULT_K = 1

_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RetrievedDocument:
    document_id: str
    score: int
    text: str


def tokenize(text: str) -> frozenset[str]:
    return frozenset(_TOKEN.findall(text.lower()))


def rank_documents(
    question: str, documents: Iterable[KnowledgeDocument], *, k: int = DEFAULT_K
) -> tuple[RetrievedDocument, ...]:
    """Rank documents by overlap without any authorization. Callers must filter first."""
    if k < 1:
        raise ValueError("k must be at least 1")
    question_tokens = tokenize(question)
    scored = [
        RetrievedDocument(
            document_id=document.id,
            score=len(question_tokens & tokenize(document.text)),
            text=document.text,
        )
        for document in documents
    ]
    ranked = sorted(
        (item for item in scored if item.score > 0),
        key=lambda item: (-item.score, item.document_id),
    )
    return tuple(ranked[:k])


def retrieve(
    question: str, role: ActorRole, access_map: DocumentAccessMap, *, k: int = DEFAULT_K
) -> tuple[RetrievedDocument, ...]:
    """Remove documents the role may not read, then rank what remains."""
    return rank_documents(question, access_map.readable_by(role), k=k)
