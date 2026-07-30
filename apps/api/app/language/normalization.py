"""Deterministic text normalization for Tamil, English, and Tanglish.

Normalization is idempotent and never changes meaning: it applies Unicode NFC
composition (so visually identical Tamil renders to one canonical form),
folds a fixed table of "smart"/full-width punctuation to ASCII equivalents,
and collapses runs of whitespace. It intentionally does *not* lowercase Tamil
(the script is caseless) and preserves the original for provenance elsewhere.
"""

from __future__ import annotations

import re
import unicodedata

# Punctuation that documents and keyboards emit in visually equivalent forms.
# Folding these makes lexical matching robust without altering meaning.
_PUNCTUATION_FOLD = {
    "\u2018": "'",  # left single quote
    "\u2019": "'",  # right single quote / apostrophe
    "\u201a": "'",  # single low quote
    "\u201c": '"',  # left double quote
    "\u201d": '"',  # right double quote
    "\u201e": '"',  # double low quote
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2015": "-",  # horizontal bar
    "\u2026": "...",  # ellipsis
    "\u00a0": " ",  # non-breaking space
    "\u200b": "",  # zero-width space
    "\u200c": "",  # zero-width non-joiner
    "\u200d": "",  # zero-width joiner
    "\ufeff": "",  # byte-order mark
}

_PUNCTUATION_PATTERN = re.compile("|".join(re.escape(key) for key in _PUNCTUATION_FOLD))
_WHITESPACE = re.compile(r"\s+")
_FULLWIDTH_START = 0xFF01
_FULLWIDTH_END = 0xFF5E
_FULLWIDTH_OFFSET = 0xFEE0


def _fold_fullwidth(text: str) -> str:
    """Map full-width ASCII variants (U+FF01..U+FF5E) to their ASCII forms."""
    return "".join(
        chr(ord(char) - _FULLWIDTH_OFFSET)
        if _FULLWIDTH_START <= ord(char) <= _FULLWIDTH_END
        else char
        for char in text
    )


def normalize_text(text: str) -> str:
    """Return the canonical form of `text`; safe to call repeatedly.

    The transform order matters: compatibility-fold width first, compose to
    NFC, fold punctuation, then collapse whitespace and trim.
    """
    folded_width = _fold_fullwidth(text)
    composed = unicodedata.normalize("NFC", folded_width)
    folded = _PUNCTUATION_PATTERN.sub(lambda match: _PUNCTUATION_FOLD[match.group()], composed)
    collapsed = _WHITESPACE.sub(" ", folded)
    return collapsed.strip()


def normalize_for_match(text: str) -> str:
    """A case-insensitive key for matching; Tamil is unaffected by casefold."""
    return normalize_text(text).casefold()


def tokenize(text: str) -> list[str]:
    """Split normalized text into words, keeping combining marks attached.

    The obvious regex — ``[^\\W_]+`` — is wrong for every abugida the platform
    supports. Python's ``\\w`` covers letters and digits but *not* the Unicode
    mark categories, and a Tamil vowel sign is a spacing combining mark (``Mc``),
    so ``விமான`` tokenizes as ``வ``, ``ம``, ``ன``: three bare consonants with the
    vowels dropped. Any two Tamil strings then share most of their "tokens", and
    a lexical overlap between unrelated passages reads as high similarity.

    So membership is decided per character: alphanumeric, or a mark of any kind
    (``Mn``/``Mc``/``Me``), which is what keeps a vowel sign bound to the
    consonant it modifies. Everything else is a separator.
    """
    words: list[str] = []
    current: list[str] = []
    for char in text:
        if char.isalnum() or unicodedata.category(char).startswith("M"):
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def match_tokens(text: str) -> set[str]:
    """The distinct tokens of `text` under the matching normalization."""
    return set(tokenize(normalize_for_match(text)))
