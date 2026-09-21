from __future__ import annotations

from enterprise_employee_agent.knowledge.access import (
    RESTRICTED_FIXTURE_ID,
    DocumentAccessMap,
    DocumentVisibility,
    KnowledgeDocument,
    load_document_access_map,
)
from enterprise_employee_agent.knowledge.retrieval import (
    rank_documents,
    retrieve,
    retrieve_for_identity,
    tokenize,
)
from enterprise_employee_agent.leave.contracts import ActorRole, DemoIdentity

US = "people-policies/leave-of-absence/us.md"
INDEX = "people-policies/leave-of-absence/_index.md"
# Chosen so that, without the filter, the synthetic HR-only note ranks first
# (overlap 10 vs us.md 8 vs _index.md 4, measured 2026-09-13).
FORBIDDEN_PROBE = "Where is the HR-only note about confidential leave investigations?"


def _doc(doc_id: str, text: str, visibility: str = "public") -> KnowledgeDocument:
    return KnowledgeDocument(id=doc_id, text=text, visibility=DocumentVisibility(visibility))


def _map(*documents: KnowledgeDocument) -> DocumentAccessMap:
    return DocumentAccessMap(access_version="t", corpus_version="t", documents=documents)


def test_tokenize_lowercases_and_splits_on_non_word_characters() -> None:
    assert tokenize("HR-only Leave, FMLA's") == frozenset({"hr", "only", "leave", "fmla", "s"})


def test_tokenize_keeps_unicode_word_characters() -> None:
    assert tokenize("Größe über") == frozenset({"größe", "über"})


def test_clear_winner_is_returned() -> None:
    documents = [_doc("a", "parental leave pay"), _doc("b", "parental")]
    assert [r.document_id for r in rank_documents("parental leave pay", documents)] == ["a"]


def test_tie_breaks_by_document_id_ascending() -> None:
    documents = [_doc("b", "leave"), _doc("a", "leave")]
    result = rank_documents("leave", documents)
    assert [(r.document_id, r.score) for r in result] == [("a", 1)]


def test_zero_overlap_returns_nothing() -> None:
    assert rank_documents("germany", [_doc("a", "united states leave")]) == ()


def test_k_limits_and_orders_results() -> None:
    documents = [_doc("a", "x"), _doc("b", "x y"), _doc("c", "x y z")]
    result = rank_documents("x y z", documents, k=2)
    assert [r.document_id for r in result] == ["c", "b"]


def test_ranking_does_not_depend_on_input_order() -> None:
    documents = [_doc("b", "leave pay"), _doc("a", "leave pay"), _doc("c", "leave")]
    assert rank_documents("leave pay", documents, k=3) == rank_documents(
        "leave pay", list(reversed(documents)), k=3
    )


def test_filter_removes_restricted_document_before_scoring() -> None:
    access_map = _map(
        _doc("public", "leave"),
        _doc("secret", "leave investigations confidential", visibility="hr_only"),
    )
    question = "confidential leave investigations"
    assert retrieve(question, ActorRole.HR, access_map)[0].document_id == "secret"
    assert [r.document_id for r in retrieve(question, ActorRole.EMPLOYEE, access_map)] == ["public"]


def test_forbidden_document_ranks_first_without_filter_and_is_absent_with_it() -> None:
    access_map = load_document_access_map()
    unfiltered = rank_documents(FORBIDDEN_PROBE, access_map.documents)
    assert unfiltered[0].document_id == RESTRICTED_FIXTURE_ID
    filtered = retrieve(
        FORBIDDEN_PROBE, ActorRole.EMPLOYEE, access_map, k=len(access_map.documents)
    )
    assert RESTRICTED_FIXTURE_ID not in {r.document_id for r in filtered}
    assert filtered[0].document_id == US


def test_retrieve_for_identity_filters_by_the_identitys_role() -> None:
    access_map = _map(
        _doc("public", "leave"),
        _doc("secret", "leave investigations confidential", visibility="hr_only"),
    )
    employee = DemoIdentity(
        identity_id="employee-alice", display_name="Alice", role=ActorRole.EMPLOYEE
    )
    hr = DemoIdentity(identity_id="hr-harper", display_name="Harper", role=ActorRole.HR)
    question = "confidential leave investigations"
    assert [r.document_id for r in retrieve_for_identity(question, employee, access_map)] == [
        "public"
    ]
    assert retrieve_for_identity(question, hr, access_map)[0].document_id == "secret"


def test_repository_cases_rank_as_the_spec_states() -> None:
    access_map = load_document_access_map()
    germany = "What's the parental leave policy for GitLab employees in Germany?"
    assert retrieve(germany, ActorRole.EMPLOYEE, access_map)[0].document_id == INDEX
    fmla = "I've worked here for 4 months, can I take FMLA leave?"
    assert retrieve(fmla, ActorRole.EMPLOYEE, access_map)[0].document_id == US
