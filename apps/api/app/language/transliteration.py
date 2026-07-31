"""Tanglish-to-Tamil transliteration behind a replaceable interface.

The MVP ships a deterministic rule-based transliterator so retrieval works
with zero external dependencies and no paid credentials. It maps common
romanized-Tamil syllables to Tamil script using a longest-match scan. This is
deliberately approximate: transliteration is a *retrieval aid*, and the
`original`/`normalized` forms remain authoritative for provenance.

Swap in a statistical or model-based transliterator later by implementing
`Transliterator`; the query pipeline depends only on the protocol.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

# Tamil is an abugida, and that is the whole difficulty here. A consonant letter
# already carries an inherent /a/; a *different* vowel is written by attaching a
# dependent sign to that consonant (ம + ீ = மீ), and a consonant with *no* vowel
# takes the virama (ம்). The same vowel has a second, independent form used only
# where a syllable starts with it (இ in இது).
#
# So a vowel cannot be transliterated in isolation — it is one character after a
# consonant and a different one at the start of a syllable. Emitting the
# independent letter in both positions produces strings that are well-formed
# Unicode and not Tamil: "vidupu" becomes வ்இட்உப்உ rather than விடுபு. That text
# renders, contains only Tamil codepoints, and matches no document ever written,
# which is why the fault survived a test asserting only that the output "contains
# Tamil".
#
# Consonants therefore map to their *base* letter, never pre-composed with a
# virama, and the scan below decides which of the two vowel forms to attach.

# Ordered longest-first so multi-character clusters win over their prefixes.
_CONSONANTS: tuple[tuple[str, str], ...] = (
    ("ndh", "ந்த"),
    ("nth", "ந்த"),
    ("kk", "க்க"),
    ("cc", "ச்ச"),
    ("tt", "ட்ட"),
    ("pp", "ப்ப"),
    ("nn", "ன்ன"),
    ("mm", "ம்ம"),
    ("ll", "ல்ல"),
    ("rr", "ற்ற"),
    ("vv", "வ்வ"),
    ("yy", "ய்ய"),
    ("zh", "ழ"),
    ("ng", "ங"),
    ("nj", "ஞ"),
    ("th", "த"),
    ("dh", "த"),
    ("sh", "ஷ"),
    ("ch", "ச"),
    ("k", "க"),
    ("g", "க"),
    ("s", "ஸ"),
    ("c", "ச"),
    ("t", "ட"),
    ("d", "ட"),
    ("n", "ன"),
    ("p", "ப"),
    ("b", "ப"),
    ("m", "ம"),
    ("y", "ய"),
    ("r", "ர"),
    ("l", "ல"),
    ("v", "வ"),
    ("w", "வ"),
    ("h", "ஹ"),
    ("j", "ஜ"),
    ("f", "ஃப"),
)

# Each vowel in both forms: the independent letter that opens a syllable, and the
# dependent sign that attaches to a preceding consonant. Short /a/ has an empty
# sign because a bare consonant already carries it — ம *is* "ma".
_VOWELS: tuple[tuple[str, str, str], ...] = (
    ("aa", "ஆ", "ா"),
    ("ee", "ஈ", "ீ"),
    ("ii", "ஈ", "ீ"),
    ("oo", "ஊ", "ூ"),
    ("uu", "ஊ", "ூ"),
    ("ai", "ஐ", "ை"),
    ("au", "ஔ", "ௌ"),
    ("a", "அ", ""),
    ("e", "எ", "ெ"),
    ("i", "இ", "ி"),
    ("o", "ஒ", "ொ"),
    ("u", "உ", "ு"),
)

_VIRAMA = "்"
_CONSONANT_LOOKUP = dict(_CONSONANTS)
_VOWEL_LOOKUP = {key: (independent, sign) for key, independent, sign in _VOWELS}
_MAX_CONSONANT = max(len(key) for key, _ in _CONSONANTS)
_MAX_VOWEL = max(len(key) for key, _, _ in _VOWELS)


@runtime_checkable
class Transliterator(Protocol):
    """Renders romanized Tamil (Tanglish) into Tamil script."""

    name: str

    def transliterate(self, text: str) -> str: ...


class RuleBasedTransliterator:
    """Longest-match romanization to Tamil script; no external dependencies."""

    name = "rule-based-v1"

    def transliterate(self, text: str) -> str:
        result: list[str] = []
        for token in text.split(" "):
            result.append(self._transliterate_word(token))
        return " ".join(result)

    def _transliterate_word(self, word: str) -> str:
        """Assemble syllables, because a Tamil vowel has no standalone form.

        Each pass takes a consonant cluster and the vowel that follows it, and
        writes them as one cluster: the consonant's base letter plus either that
        vowel's dependent sign or, when no vowel follows, the virama. A vowel
        reached with no consonant in front of it opens a syllable and takes its
        independent form instead.
        """
        if not word:
            return word
        lowered = word.casefold()
        # Non-Latin words (already Tamil, digits, punctuation) pass through.
        if not any(char.isascii() and char.isalpha() for char in lowered):
            return word
        out: list[str] = []
        index = 0
        length = len(lowered)
        while index < length:
            char = lowered[index]
            if not (char.isascii() and char.isalpha()):
                out.append(word[index])
                index += 1
                continue
            consonant, consumed = self._match(lowered, index, _CONSONANT_LOOKUP, _MAX_CONSONANT)
            if consonant is not None:
                index += consumed
                out.append(consonant)
                vowel, vowel_consumed = self._match(lowered, index, _VOWEL_LOOKUP, _MAX_VOWEL)
                if vowel is None:
                    # No vowel follows, so the consonant is bare: ம் not ம.
                    out.append(_VIRAMA)
                else:
                    index += vowel_consumed
                    # `sign` is empty for short /a/ — the bare consonant is
                    # already "ma", and appending anything would double the vowel.
                    out.append(vowel[1])
                continue
            vowel, consumed = self._match(lowered, index, _VOWEL_LOOKUP, _MAX_VOWEL)
            if vowel is not None:
                index += consumed
                out.append(vowel[0])
                continue
            out.append(word[index])  # pragma: no cover - tables cover a..z
            index += 1
        return "".join(out)

    @staticmethod
    def _match[T](
        text: str, index: int, table: Mapping[str, T], longest: int
    ) -> tuple[T | None, int]:
        """Longest-first lookup at `index`, with the number of characters used."""
        for size in range(min(longest, len(text) - index), 0, -1):
            found = table.get(text[index : index + size])
            if found is not None:
                return found, size
        return None, 0


def get_default_transliterator() -> Transliterator:
    """The provider used by the query pipeline unless one is injected."""
    return RuleBasedTransliterator()
