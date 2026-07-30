"""Tamil must survive tokenization in every module that tokenizes.

The defect this guards against is not a crash and not a wrong answer in
English — it is silent, and it flatters. ``[^\\W_]+`` looks correct and is the
idiom every one of these modules reached for independently. Python's ``\\w``
covers letters and digits but not the Unicode mark categories, and a Tamil vowel
sign is a spacing combining mark, so ``விமான`` tokenizes to the bare consonants
``வ``, ``ம``, ``ன``. Vowels are dropped, words collapse to their skeletons, and
two Tamil sentences with nothing in common share most of their "tokens".

Everything downstream then reads as confident: retrieval scores unrelated
passages as near-identical, the reranker agrees, the verifier's lexical-overlap
signal inflates the confidence of a claim against evidence that does not support
it, and the embeddings put all Tamil text in roughly one corner of the vector
space. Nothing fails. The numbers simply stop meaning anything.

So each test pairs two Tamil strings that genuinely share nothing and asserts the
module can tell them apart — with a near-paraphrase alongside, so a module that
had merely learned to score all Tamil at zero would fail these too.
"""

from __future__ import annotations

import uuid

from app.embeddings.provider import LocalHashingEmbeddingProvider
from app.language import match_tokens, tokenize
from app.rag.generation import ExtractiveGenerator
from app.reranking.provider import LocalLexicalReranker
from app.reranking.types import RerankItem
from app.verification.signals import extract_signals

# "How much is the airfare?" against "Employee leave accrues every month."
AIRFARE = "விமான டிக்கெட் விலை எவ்வளவு"
LEAVE = "ஊழியர் விடுப்பு ஒவ்வொரு மாதமும் சேர்க்கப்படும்"
# A near-paraphrase of LEAVE: same subject, one verb changed.
LEAVE_RELATED = "ஊழியர் விடுப்பு ஒவ்வொரு மாதமும் வழங்கப்படும்"


def test_the_shared_tokenizer_keeps_words_whole() -> None:
    assert tokenize(AIRFARE) == ["விமான", "டிக்கெட்", "விலை", "எவ்வளவு"]
    # The old regex reduced this to {'வ', 'ம', 'ன', …}, which is precisely why
    # every module below could confuse these two sentences.
    assert not match_tokens(AIRFARE) & match_tokens(LEAVE)
    assert match_tokens(LEAVE) & match_tokens(LEAVE_RELATED)


def rerank(query: str, passage: str) -> float:
    scores = LocalLexicalReranker().score(query, [RerankItem(chunk_id=uuid.uuid4(), text=passage)])
    return scores[0].score


def test_the_reranker_separates_unrelated_tamil() -> None:
    """Otherwise reranking a Tamil query barely changes the candidate order."""
    unrelated = rerank(AIRFARE, LEAVE)
    related = rerank(LEAVE, LEAVE_RELATED)

    assert unrelated < related
    assert unrelated < 0.3


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def test_embeddings_place_unrelated_tamil_further_apart_than_related() -> None:
    """Character trigrams still overlap; whole words are what pull them apart."""
    provider = LocalHashingEmbeddingProvider()
    airfare, leave, related = provider.embed([AIRFARE, LEAVE, LEAVE_RELATED]).vectors

    assert cosine(leave.values, related.values) > cosine(airfare.values, leave.values)


def test_the_embedding_version_moved_with_the_tokenizer() -> None:
    """The version scopes every vector search, so a feature change has to move it.

    `EmbeddingRepository.search` filters on `model` and `model_version`. Had the
    version stayed, vectors written under the old tokenizer would have gone on
    being compared against queries embedded under the new one — a silently wrong
    nearest neighbour rather than a visible mismatch.
    """
    assert LocalHashingEmbeddingProvider().model_version == "hashing-v2"


def test_claim_signals_extract_whole_tamil_words() -> None:
    """Content tokens are what the verifier's lexical coverage is computed over."""
    leave = extract_signals(LEAVE)
    airfare = extract_signals(AIRFARE)

    assert "ஊழியர்" in leave.tokens
    assert not airfare.content_tokens & leave.content_tokens
    assert extract_signals(LEAVE_RELATED).content_tokens & leave.content_tokens


def test_generation_scores_unrelated_tamil_below_a_paraphrase() -> None:
    """Candidate selection is lexical, so consonant skeletons made anything a match."""
    generator = ExtractiveGenerator()

    unrelated = generator._coverage(generator._tokens(AIRFARE), LEAVE)  # noqa: SLF001
    related = generator._coverage(generator._tokens(LEAVE), LEAVE_RELATED)  # noqa: SLF001

    assert unrelated < related
