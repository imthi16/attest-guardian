"""Deterministic chunking behavior: structure, overlap, offsets, provenance."""

import hashlib

import pytest
from app.chunking.chunker import ChunkDraft, PageInput, chunk_page, chunk_pages, count_tokens
from app.chunking.provenance import ProvenanceError, validate_chunk_provenance

TAMIL_PARAGRAPH = "வணக்கம் உலகம். இது ஒரு நீண்ட தமிழ் பத்தி ஆகும், சான்றுகளை சரியாக மேற்கோள் காட்டுவதற்கான சோதனை."


def page(text: str, number: int = 1, **metadata: object) -> PageInput:
    return PageInput(page_number=number, text=text, **metadata)  # type: ignore[arg-type]


def chunks_of(text: str, *, max_chars: int = 200, overlap: int = 20) -> list[ChunkDraft]:
    drafts, _ = chunk_page(page(text), max_chars=max_chars, overlap=overlap)
    return drafts


class TestStructure:
    def test_paragraphs_pack_into_one_chunk_when_small(self) -> None:
        drafts = chunks_of("First paragraph.\n\nSecond paragraph.", max_chars=200)
        assert len(drafts) == 1
        assert "First paragraph." in drafts[0].content
        assert "Second paragraph." in drafts[0].content

    def test_paragraph_boundaries_are_respected_when_full(self) -> None:
        first = "alpha " * 15
        second = "beta " * 15
        drafts = chunks_of(f"{first.strip()}\n\n{second.strip()}", max_chars=110, overlap=0)
        assert len(drafts) == 2
        assert "beta" not in drafts[0].content
        assert "alpha" not in drafts[1].content

    def test_markdown_headings_build_the_section_hierarchy(self) -> None:
        text = (
            "# Introduction\n\nIntro paragraph body.\n\n"
            "## Background\n\nBackground paragraph body.\n\n"
            "# Conclusion\n\nConcluding paragraph body."
        )
        drafts = chunks_of(text, max_chars=90, overlap=0)
        sections = [draft.section for draft in drafts]
        assert sections == ["Introduction", "Introduction > Background", "Conclusion"]

    def test_numbered_headings_are_recognized(self) -> None:
        text = "1. Scope\n\nScope body text here.\n\n1.1 Details\n\nDetail body text here."
        drafts = chunks_of(text, max_chars=60, overlap=0)
        assert [draft.section for draft in drafts] == ["1. Scope", "1. Scope > 1.1 Details"]

    def test_heading_line_starts_its_chunk(self) -> None:
        drafts = chunks_of("# Title\n\nBody paragraph.", max_chars=200)
        assert drafts[0].content.startswith("# Title")

    def test_pipe_tables_stay_atomic_even_when_oversized(self) -> None:
        table = "\n".join(f"| row {i} | value {i} |" for i in range(30))
        text = f"Intro paragraph.\n\n{table}\n\nOutro paragraph."
        drafts = chunks_of(text, max_chars=120, overlap=0)
        table_chunks = [d for d in drafts if "| row 0 |" in d.content]
        assert len(table_chunks) == 1
        assert "| row 29 |" in table_chunks[0].content
        assert "Intro" not in table_chunks[0].content


class TestSizeAndOverlap:
    def test_oversized_paragraph_splits_with_overlap(self) -> None:
        words = " ".join(f"word{i:03d}" for i in range(120))
        drafts = chunks_of(words, max_chars=200, overlap=40)
        assert len(drafts) > 2
        for draft in drafts:
            assert len(draft.content) <= 200
        for previous, current in zip(drafts, drafts[1:], strict=False):
            assert current.char_start < previous.char_end  # genuine overlap
        assert drafts[-1].char_end == len(words)

    def test_packed_chunks_share_overlap_context(self) -> None:
        first = "alpha " * 15
        second = "beta " * 15
        text = f"{first.strip()}\n\n{second.strip()}"
        drafts = chunks_of(text, max_chars=110, overlap=30)
        assert len(drafts) == 2
        assert drafts[1].char_start < drafts[0].char_end

    def test_invalid_configuration_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="max_chars"):
            chunk_page(page("body"), max_chars=100, overlap=100)


class TestOffsetsAndMetadata:
    def test_content_is_always_the_exact_source_span(self) -> None:
        text = f"# தலைப்பு\n\n{TAMIL_PARAGRAPH}\n\nஇன்னொரு பத்தி இங்கே."
        for draft in chunks_of(text, max_chars=80, overlap=10):
            assert text[draft.char_start : draft.char_end] == draft.content

    def test_page_and_ocr_metadata_are_carried(self) -> None:
        source = PageInput(
            page_number=3,
            text=TAMIL_PARAGRAPH,
            language="ta",
            ocr_engine="tesseract",
            ocr_confidence=0.91,
        )
        drafts, _ = chunk_page(source, max_chars=500, overlap=50)
        assert drafts[0].page_number == 3
        assert drafts[0].language == "ta"
        assert drafts[0].ocr_engine == "tesseract"
        assert drafts[0].ocr_confidence == 0.91

    def test_token_counts_match_the_documented_approximation(self) -> None:
        drafts = chunks_of("one two three\n\nநான்கு ஐந்து", max_chars=500)
        assert drafts[0].token_count == count_tokens(drafts[0].content) == 5

    def test_empty_and_whitespace_pages_produce_no_chunks(self) -> None:
        assert chunks_of("") == []
        assert chunks_of(" \n\n \t\n") == []

    def test_chunking_is_deterministic(self) -> None:
        text = f"# Title\n\n{TAMIL_PARAGRAPH}\n\n" + "filler " * 100
        assert chunks_of(text, max_chars=150, overlap=25) == chunks_of(
            text, max_chars=150, overlap=25
        )


class TestPageSpanning:
    def test_sections_carry_across_pages_but_chunks_do_not(self) -> None:
        pages = [
            PageInput(page_number=1, text="# Chapter One\n\nFirst page paragraph body."),
            PageInput(page_number=2, text="Continuation paragraph on the second page."),
        ]
        drafts = chunk_pages(pages, max_chars=500, overlap=50)
        assert [draft.page_number for draft in drafts] == [1, 2]
        assert drafts[0].section == "Chapter One"
        assert drafts[1].section == "Chapter One"  # hierarchy survives the page break
        for draft, source in zip(drafts, pages, strict=True):
            assert source.text[draft.char_start : draft.char_end] == draft.content


class TestProvenanceValidation:
    def make_valid(self) -> tuple[ChunkDraft, str]:
        text = "A paragraph that will validate cleanly."
        drafts = chunks_of(text, max_chars=500)
        return drafts[0], text

    def test_valid_chunk_passes(self) -> None:
        draft, text = self.make_valid()
        validate_chunk_provenance(draft, text)

    def test_tampered_content_is_rejected(self) -> None:
        draft, text = self.make_valid()
        tampered = ChunkDraft(**{**draft.__dict__, "content": draft.content + " EXTRA"})
        with pytest.raises(ProvenanceError, match="span|bounds"):
            validate_chunk_provenance(tampered, text)

    def test_wrong_hash_is_rejected(self) -> None:
        draft, text = self.make_valid()
        tampered = ChunkDraft(**{**draft.__dict__, "content_hash": "0" * 64})
        with pytest.raises(ProvenanceError, match="hash"):
            validate_chunk_provenance(tampered, text)

    def test_out_of_bounds_span_is_rejected(self) -> None:
        draft, text = self.make_valid()
        tampered = ChunkDraft(**{**draft.__dict__, "char_end": len(text) + 5})
        with pytest.raises(ProvenanceError, match="bounds"):
            validate_chunk_provenance(tampered, text)

    def test_wrong_token_count_is_rejected(self) -> None:
        draft, text = self.make_valid()
        tampered = ChunkDraft(**{**draft.__dict__, "token_count": 999})
        with pytest.raises(ProvenanceError, match="token"):
            validate_chunk_provenance(tampered, text)

    def test_empty_content_is_rejected(self) -> None:
        draft, text = self.make_valid()
        empty = ChunkDraft(**{**draft.__dict__, "content": "  ", "char_end": draft.char_start + 2})
        with pytest.raises(ProvenanceError, match="empty"):
            validate_chunk_provenance(empty, text)

    def test_bad_page_number_is_rejected(self) -> None:
        draft, text = self.make_valid()
        tampered = ChunkDraft(**{**draft.__dict__, "page_number": 0})
        with pytest.raises(ProvenanceError, match="page"):
            validate_chunk_provenance(tampered, text)

    def test_out_of_range_confidence_is_rejected(self) -> None:
        draft, text = self.make_valid()
        tampered = ChunkDraft(**{**draft.__dict__, "ocr_confidence": 1.5})
        with pytest.raises(ProvenanceError, match="confidence"):
            validate_chunk_provenance(tampered, text)

    def test_hash_matches_sha256_of_content(self) -> None:
        draft, _ = self.make_valid()
        assert draft.content_hash == hashlib.sha256(draft.content.encode()).hexdigest()
