"""Deterministic language detection, normalization, and query processing.

Covers the PR 9 acceptance fixtures: Tamil Unicode, mixed-script, Tanglish,
English, punctuation, and ambiguity — asserting the original query is always
retained and that confidence/limitations are exposed.
"""

from __future__ import annotations

import unicodedata

import pytest
from app.language import (
    Language,
    ProcessedQuery,
    QueryProcessor,
    detect_language,
    get_default_query_processor,
    normalize_for_match,
    normalize_text,
)
from app.language.spelling import DictionarySpellingNormalizer
from app.language.transliteration import RuleBasedTransliterator

TAMIL_HELLO = "வணக்கம்"
TAMIL_SENTENCE = "எனது ஆவணத்தின் கொள்கை என்ன?"


class TestNormalization:
    def test_nfc_composition_is_canonical(self) -> None:
        # Tamil vowel sign "o" (U+0BCA) decomposes into two codepoints under
        # NFD; normalization must recompose it to the single canonical form.
        composed = "கொள்கை"
        decomposed = unicodedata.normalize("NFD", composed)
        assert decomposed != composed  # precondition: input is decomposed
        assert normalize_text(decomposed) == unicodedata.normalize("NFC", composed)

    def test_smart_punctuation_folds_to_ascii(self) -> None:
        assert normalize_text("\u201cquote\u201d") == '"quote"'
        assert normalize_text("it\u2019s") == "it's"
        assert normalize_text("a\u2014b") == "a-b"
        assert normalize_text("wait\u2026") == "wait..."

    def test_fullwidth_ascii_is_folded(self) -> None:
        assert normalize_text("\uff28\uff45\uff4c\uff4c\uff4f") == "Hello"

    def test_zero_width_and_bom_are_removed(self) -> None:
        assert normalize_text("a\u200bb\ufeffc") == "abc"

    def test_whitespace_is_collapsed_and_trimmed(self) -> None:
        assert normalize_text("  a\t\n  b  ") == "a b"

    def test_normalization_is_idempotent(self) -> None:
        once = normalize_text("  \u201cHello\u201d\u2014world  ")
        assert normalize_text(once) == once

    def test_normalize_for_match_casefolds_latin_only(self) -> None:
        assert normalize_for_match("Refund POLICY") == "refund policy"
        # Tamil is caseless: casefolding must not alter the codepoints.
        assert normalize_for_match(TAMIL_HELLO) == TAMIL_HELLO


class TestTamilDetection:
    def test_pure_tamil_is_high_confidence(self) -> None:
        result = detect_language(TAMIL_SENTENCE)
        assert result.language is Language.TAMIL
        assert result.confidence >= 0.9
        assert result.limitations == ()

    def test_tamil_with_digits_and_punctuation_still_tamil(self) -> None:
        result = detect_language("2024 ஆம் ஆண்டு கொள்கை என்ன?")
        assert result.language is Language.TAMIL

    def test_detection_metadata_is_json_safe(self) -> None:
        meta = detect_language(TAMIL_SENTENCE).as_metadata()
        assert meta["language"] == "tam"
        confidence = meta["confidence"]
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0
        assert isinstance(meta["limitations"], list)


class TestEnglishDetection:
    def test_plain_english(self) -> None:
        result = detect_language("What is the refund policy for late orders?")
        assert result.language is Language.ENGLISH
        assert result.confidence >= 0.7

    def test_english_with_punctuation_is_not_diluted(self) -> None:
        result = detect_language('Order #12 — "ready" now?')
        assert result.language is Language.ENGLISH


class TestTanglishDetection:
    def test_romanized_tamil_is_tanglish(self) -> None:
        result = detect_language("vanakkam, eppadi irukku? venum")
        assert result.language is Language.TANGLISH
        assert result.confidence >= 0.6

    def test_weak_marker_is_tanglish_but_flagged(self) -> None:
        result = detect_language("please seri the document now")
        assert result.language is Language.TANGLISH
        assert any("ambiguous" in note for note in result.limitations)


class TestMixedAndAmbiguous:
    def test_mixed_script_is_flagged(self) -> None:
        result = detect_language("இந்த document எங்க இருக்கு")
        assert "mixed Tamil and Latin script" in result.limitations

    def test_mixed_latin_dominant_with_marker_is_tanglish(self) -> None:
        # Both scripts above the mix threshold, Latin dominant, marker present.
        result = detect_language("eppadi venum இந்த ஆவணம்")
        assert result.language is Language.TANGLISH
        assert "mixed Tamil and Latin script" in result.limitations

    def test_mixed_latin_dominant_without_marker_is_english(self) -> None:
        # Both scripts above the mix threshold, Latin dominant, no marker.
        result = detect_language("review report இந்த ஆவணம்")
        assert result.language is Language.ENGLISH
        assert "mixed Tamil and Latin script" in result.limitations

    def test_accented_latin_is_treated_as_latin(self) -> None:
        # Non-ASCII Latin letters must still count toward the Latin ratio.
        result = detect_language("café résumé naïve")
        assert result.language is Language.ENGLISH
        assert result.script.latin_ratio > 0.9

    def test_empty_and_numeric_are_unknown(self) -> None:
        for text in ("", "   ", "12345", "!!!"):
            result = detect_language(text)
            assert result.language is Language.UNKNOWN
            assert result.confidence == 0.0
            assert result.limitations

    def test_very_short_input_is_low_confidence(self) -> None:
        result = detect_language("ok")
        assert result.confidence <= 0.5
        assert any("short" in note for note in result.limitations)

    def test_ambiguous_words_do_not_force_tanglish(self) -> None:
        # "no" / "an" are shared function words; must stay English.
        assert detect_language("an item is no good").language is Language.ENGLISH


class TestNormalizationComponents:
    # Expected strings, not a Unicode-range check. "Contains a character in
    # the Tamil block" is satisfied by consonant-virama-vowel runs that are
    # well-formed Unicode, are not Tamil, and match no document - which is
    # how a broken transliterator passed this suite for so long.
    @pytest.mark.parametrize(
        ("romanized", "tamil"),
        [
            ("viduppu", "\u0bb5\u0bbf\u0b9f\u0bc1\u0baa\u0bcd\u0baa\u0bc1"),
            ("eettiya", "\u0b88\u0b9f\u0bcd\u0b9f\u0bbf\u0baf"),
            ("enna", "\u0b8e\u0ba9\u0bcd\u0ba9"),
            ("irukku", "\u0b87\u0bb0\u0bc1\u0b95\u0bcd\u0b95\u0bc1"),
            ("eppadi", "\u0b8e\u0baa\u0bcd\u0baa\u0b9f\u0bbf"),
        ],
    )
    def test_transliterator_writes_real_tamil_clusters(self, romanized: str, tamil: str) -> None:
        assert RuleBasedTransliterator().transliterate(romanized) == tamil

    def test_a_vowel_after_a_consonant_is_a_sign_not_a_letter(self) -> None:
        """The defect itself, pinned.

        Tamil writes consonant+vowel as one cluster (\u0bb5 + \u0bbf = \u0bb5\u0bbf). Emitting the
        *independent* vowel instead (\u0bb5\u0bcd + \u0b87) yields text that renders and can
        never match a document, so the independent forms must not appear here.
        """
        out = RuleBasedTransliterator().transliterate("vidupu")
        assert out == "\u0bb5\u0bbf\u0b9f\u0bc1\u0baa\u0bc1"
        assert not any(vowel in out for vowel in ("\u0b85", "\u0b87", "\u0b89", "\u0b8e", "\u0b92"))

    def test_a_vowel_opening_a_syllable_keeps_its_independent_form(self) -> None:
        """The other half: word-initial vowels have no consonant to attach to."""
        assert RuleBasedTransliterator().transliterate("ethanai") == "\u0b8e\u0ba4\u0ba9\u0bc8"

    def test_a_trailing_consonant_takes_the_virama(self) -> None:
        assert RuleBasedTransliterator().transliterate("naal").endswith("\u0bcd")

    def test_transliterator_passes_through_non_latin(self) -> None:
        assert RuleBasedTransliterator().transliterate(TAMIL_HELLO) == TAMIL_HELLO

    def test_transliterator_preserves_digits_and_spacing(self) -> None:
        out = RuleBasedTransliterator().transliterate("test 12")
        assert "12" in out
        assert " " in out

    def test_spelling_normalizer_folds_known_variants(self) -> None:
        normalizer = DictionarySpellingNormalizer()
        assert normalizer.normalize("epdi") == "eppadi"
        assert normalizer.normalize("epadi pannuga") == "eppadi pannunga"

    def test_spelling_normalizer_passes_unknown_tokens(self) -> None:
        assert DictionarySpellingNormalizer().normalize("hello world") == "hello world"

    def test_custom_variant_table_is_respected(self) -> None:
        normalizer = DictionarySpellingNormalizer({"foo": "bar"})
        assert normalizer.normalize("foo baz") == "bar baz"


class TestQueryProcessor:
    @pytest.fixture
    def processor(self) -> QueryProcessor:
        return get_default_query_processor()

    def test_original_is_always_retained_verbatim(self, processor: QueryProcessor) -> None:
        raw = "  eppadi \u201cregister\u201d panna?  "
        assert processor.process(raw).original == raw

    def test_english_query_has_no_transliteration_noise(self, processor: QueryProcessor) -> None:
        result = processor.process("refund policy")
        assert result.normalized == "refund policy"
        assert result.transliterated == "refund policy"
        assert result.expansions == ()

    def test_tamil_query_transliteration_equals_normalized(self, processor: QueryProcessor) -> None:
        result = processor.process(TAMIL_SENTENCE)
        assert result.detection.language is Language.TAMIL
        assert result.transliterated == result.normalized

    def test_tanglish_query_produces_tamil_script_variant(self, processor: QueryProcessor) -> None:
        result = processor.process("vanakkam eppadi irukku venum")
        assert result.detection.language is Language.TANGLISH
        assert any("\u0b80" <= ch <= "\u0bff" for ch in result.transliterated)
        assert result.transliterated in result.search_variants

    def test_tanglish_spelling_variant_becomes_expansion(self, processor: QueryProcessor) -> None:
        result = processor.process("epdi register panna venum")
        # The spelling-corrected romanized form is kept as an extra candidate.
        assert any("eppadi" in variant for variant in result.expansions)

    def test_search_variants_are_deduplicated_and_ordered(self, processor: QueryProcessor) -> None:
        result = processor.process("refund policy")
        assert result.search_variants == ("refund policy",)

    def test_metadata_round_trips_all_representations(self, processor: QueryProcessor) -> None:
        meta = processor.process("vanakkam venum").as_metadata()
        assert set(meta) == {
            "original",
            "normalized",
            "transliterated",
            "expansions",
            "detection",
        }
        assert isinstance(meta["detection"], dict)

    def test_providers_are_injectable(self) -> None:
        class ShoutTransliterator:
            name = "shout"

            def transliterate(self, text: str) -> str:
                return text.upper()

        processor = QueryProcessor(transliterator=ShoutTransliterator())
        result = processor.process("vanakkam venum irukku eppadi")
        assert result.transliterated == result.transliterated.upper()

    def test_processed_query_is_immutable(self, processor: QueryProcessor) -> None:
        result = processor.process("refund policy")
        assert isinstance(result, ProcessedQuery)
        with pytest.raises((AttributeError, TypeError)):
            result.normalized = "tampered"  # type: ignore[misc]


def test_tokenize_keeps_tamil_vowel_signs_on_their_consonant() -> None:
    """The regex every module reached for shatters Tamil into bare consonants.

    Python's `\\w` covers letters and digits but not the Unicode mark categories,
    and a Tamil vowel sign is a spacing combining mark, so `[^\\W_]+` tokenizes
    `விமான` as `வ`, `ம`, `ன`. Two unrelated Tamil passages then share most of
    their "tokens", and lexical overlap between them reads as high similarity.
    """
    from app.language import match_tokens, tokenize

    assert tokenize("விமான டிக்கெட் விலை") == ["விமான", "டிக்கெட்", "விலை"]
    # The failure this prevents: unrelated Tamil sentences sharing nothing.
    assert not match_tokens("விமான டிக்கெட் விலை") & match_tokens("ஊழியர் விடுப்பு சேர்க்கப்படும்")


def test_tokenize_handles_latin_and_mixed_script() -> None:
    from app.language import tokenize

    assert tokenize("Payment thirty days la pannanum, illena penalty!") == [
        "Payment",
        "thirty",
        "days",
        "la",
        "pannanum",
        "illena",
        "penalty",
    ]
    assert tokenize("ஒப்பந்தம் March 2026") == ["ஒப்பந்தம்", "March", "2026"]
    assert tokenize("") == []
    assert tokenize("   ---   ") == []
