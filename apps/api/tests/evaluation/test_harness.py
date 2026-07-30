"""The substitutions the harness makes, and the boundaries they have to hold.

Only the data layer is faked, so the parts that are faked need their own tests:
a retriever that quietly served another workspace, or a provenance reader that
resolved anything asked of it, would make every downstream number meaningless
while every suite stayed green.
"""

from __future__ import annotations

import asyncio
import uuid

from app.citations.resolver import CitationResolver
from app.citations.types import CitationError, CitationReference
from app.evaluation.datasets import QueryCase, load_datasets
from app.evaluation.harness import (
    CorpusProvenanceReader,
    CorpusRetriever,
    chunk_uuid,
    overlap,
    run_query,
    workspace_uuid,
)

DATASETS = load_datasets()


def retrieve(workspace: str, query: str, top_k: int = 8) -> list[str]:
    retriever = CorpusRetriever(DATASETS, workspace)
    passages, _ = asyncio.run(
        retriever.retrieve(
            workspace_id=workspace_uuid(workspace),
            query=query,
            top_k=top_k,
            document_id=None,
            language=None,
        )
    )
    by_uuid = {chunk_uuid(chunk.chunk_id): chunk.chunk_id for chunk in DATASETS.corpus}
    return [by_uuid[passage.chunk_id] for passage in passages]


def test_the_retriever_never_serves_another_workspace_passage() -> None:
    """The substitution for repository scoping, so it is checked rather than trusted."""
    beta_ids = {chunk.chunk_id for chunk in DATASETS.workspace_corpus("beta")}

    # Worded to match beta's passage exactly; alpha's reader still gets alpha's.
    served = retrieve("alpha", "invoice payment due within sixty days of receipt")

    assert served
    assert not set(served) & beta_ids


def test_an_empty_query_matches_nothing_rather_than_everything() -> None:
    """Dividing by a zero token count would otherwise make every passage relevant."""
    assert overlap("", "any text at all") == 0.0
    assert retrieve("alpha", "   ") == []


def test_ranking_is_deterministic_across_runs() -> None:
    """A reproducible number needs a stable order, including among ties."""
    first = retrieve("alpha", "annual leave accrues monthly")
    second = retrieve("alpha", "annual leave accrues monthly")

    assert first == second


def test_top_k_bounds_what_reaches_generation() -> None:
    assert len(retrieve("alpha", "payment", top_k=1)) <= 1


def test_provenance_is_unreadable_across_the_workspace_boundary() -> None:
    """Returning `None` is what lets a resolved citation prove authorization.

    A reader that resolved any chunk asked of it would make citation resolution
    a formality, and the isolation metric would pass on nothing.
    """
    reader = CorpusProvenanceReader(DATASETS, "alpha")

    own = asyncio.run(reader.get_provenance(chunk_uuid("alpha-invoice-terms")))
    foreign = asyncio.run(reader.get_provenance(chunk_uuid("beta-invoice-terms")))
    unknown = asyncio.run(reader.get_provenance(uuid.uuid4()))

    assert own is not None
    assert own.content == DATASETS.chunk("alpha-invoice-terms").text
    assert foreign is None
    assert unknown is None


def test_a_citation_into_another_workspace_is_counted_as_unresolvable() -> None:
    """The failure the harness has to be able to see, so it is provoked directly."""
    resolver = CitationResolver(CorpusProvenanceReader(DATASETS, "alpha"))
    foreign = DATASETS.chunk("beta-invoice-terms")
    reference = CitationReference(
        chunk_id=chunk_uuid(foreign.chunk_id),
        document_version_id=chunk_uuid(f"{foreign.document}:v1"),
        quote=foreign.text[:10],
        quote_char_start=0,
        quote_char_end=10,
    )

    try:
        asyncio.run(resolver.resolve(reference))
    except CitationError as error:
        assert "does not exist in this workspace" in str(error)
    else:  # pragma: no cover - the assertion above is the expected path
        raise AssertionError("a cross-workspace citation resolved")


def test_a_refused_query_is_not_counted_as_correct() -> None:
    """Otherwise "answered nothing" and "answered right" would score the same."""
    case = QueryCase(
        query_id="probe",
        text="who won the football world cup",
        language="eng",
        answerable=True,  # mislabelled on purpose: the evidence does not exist
        relevance={},
        expected_quote="anything",
        note="a question the corpus cannot answer, labelled as if it could",
    )

    result = asyncio.run(run_query(DATASETS, case))

    assert result.abstained
    assert not result.correct
    assert not result.faithful


def test_an_answer_with_no_citation_is_not_faithful() -> None:
    """Faithfulness is grounding, so citing nothing cannot satisfy it by default."""
    case = QueryCase(
        query_id="probe",
        text="invoice payment due date",
        language="eng",
        answerable=True,
        relevance={"alpha-invoice-terms": 2},
        expected_quote="thirty days",
        note="a normal answerable query",
    )

    result = asyncio.run(run_query(DATASETS, case))

    assert result.cited_ids
    assert result.faithful
