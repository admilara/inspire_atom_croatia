# SPDX-License-Identifier: GPL-3.0-or-later
"""Croatian-aware sorting and diacritic-insensitive searching.

Qt sorts table cells by Unicode code point, which puts Č, Ć, Đ, Š and Ž
after Z. hr_sort_key() follows the Croatian alphabet instead, including the
digraphs dž, lj and nj, and gives the same order on every operating system
(QCollator's result depends on the platform and the Qt build).
"""

import unicodedata

# Croatian alphabet, with q, w, x and y slotted into their Latin positions so
# that foreign names still sort sensibly.
_ALPHABET = [
    "a", "b", "c", "č", "ć", "d", "dž", "đ", "e", "f", "g", "h", "i", "j",
    "k", "l", "lj", "m", "n", "nj", "o", "p", "q", "r", "s", "š", "t", "u",
    "v", "w", "x", "y", "z", "ž",
]
_LETTER_BASE = 100
_RANK = {letter: _LETTER_BASE + i for i, letter in enumerate(_ALPHABET)}
_DIGRAPHS = {"dž", "lj", "nj"}
_DIGIT_BASE = 10
_UNKNOWN_BASE = 1000


def _tokens(text):
    """Split lower-cased text into Croatian letters (digraphs count as one)."""
    i = 0
    while i < len(text):
        pair = text[i:i + 2]
        if pair in _DIGRAPHS:
            yield pair
            i += 2
        else:
            yield text[i]
            i += 1


def _rank(token):
    if token in _RANK:
        return _RANK[token]
    if token.isspace():
        return 0
    if token.isdigit():
        return _DIGIT_BASE + int(token) if token.isascii() else _UNKNOWN_BASE + ord(token)
    if unicodedata.category(token).startswith("P"):
        return 1
    return _UNKNOWN_BASE + ord(token)


def hr_sort_key(text):
    """Sort key ordering strings by the Croatian alphabet, case-insensitively.

    The original string is appended as a tie-breaker so the order is total
    and stable (e.g. "Brač" and "BRAČ" do not compare equal).
    """
    normalized = unicodedata.normalize("NFC", text or "").lower()
    return tuple(_rank(t) for t in _tokens(normalized)), text or ""


def fold_for_search(text):
    """Lower-case and strip diacritics: 'Đurđevac Čakovec' -> 'durdevac cakovec'.

    Đ/đ has no Unicode decomposition, so it is mapped explicitly.
    """
    text = (text or "").lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def matches_search(query, *fields):
    """True if every word of the query occurs in at least one of the fields.

    A query typed without diacritics matches with or without them ("cakovec"
    finds ČAKOVEC). A query that does contain diacritics is matched exactly,
    so "ča" finds ČAKOVEC but not LJUBEŠĆICA.
    """
    query = unicodedata.normalize("NFC", query or "").lower()
    folded_query = fold_for_search(query)
    if folded_query == query:
        words = folded_query.split()
        haystack = " ".join(fold_for_search(f) for f in fields)
    else:
        words = query.split()
        haystack = " ".join(unicodedata.normalize("NFC", f or "").lower() for f in fields)
    return all(word in haystack for word in words)
