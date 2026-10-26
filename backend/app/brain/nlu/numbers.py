"""Spoken numbers and time phrases to digits ("seven thirty" -> "7:30")."""

import re

_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
# "one" after these is a pronoun ("the second one"), not the number 1.
_ONE_BLOCKERS = frozenset({
    "the", "that", "this", "which", "other", "another", "any", "each", "every", "first",
    "second", "third", "last", "no",
})
_OH_RUN_MIN_DIGITS = 5


def _read_number(tokens: list[str], i: int) -> tuple[int, int] | None:
    """Read a number word at tokens[i]; return (value, tokens used)."""
    tok = tokens[i]
    if tok in _TENS:
        if i + 1 < len(tokens) and tokens[i + 1] in _UNITS and 1 <= _UNITS[tokens[i + 1]] <= 9:
            return _TENS[tok] + _UNITS[tokens[i + 1]], 2
        return _TENS[tok], 1
    if tok in _UNITS:
        return _UNITS[tok], 1
    return None


def _read_minutes(tokens: list[str], i: int) -> tuple[int, int] | None:
    """Read minutes (10-59, or "oh five") following an hour word."""
    if i >= len(tokens):
        return None
    if tokens[i] == "oh" and i + 1 < len(tokens) and tokens[i + 1] in _UNITS:
        unit = _UNITS[tokens[i + 1]]
        if 1 <= unit <= 9:
            return unit, 2
        return None
    got = _read_number(tokens, i)
    if got and 10 <= got[0] <= 59:
        return got
    return None


def _words_to_digits(text: str) -> str:
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        got = _read_number(tokens, i)
        if got is None or (tok == "one" and out and out[-1] in _ONE_BLOCKERS):
            out.append(tok)
            i += 1
            continue
        value, used = got
        i += used
        if used == 1 and tok in _UNITS and 1 <= value <= 12:
            minutes = _read_minutes(tokens, i)
            if minutes:
                out.append(f"{value}:{minutes[0]:02d}")
                i += minutes[1]
                continue
        out.append(str(value))
    return " ".join(out)


def _quarter_to(match: re.Match[str]) -> str:
    hour = int(match.group(1))
    return f"{hour - 1 if hour > 1 else 12}:45"


def _fix_oh_runs(text: str) -> str:
    """Inside long digit runs (phone numbers) read "oh" as 0."""
    tokens = text.split()
    i = 0
    while i < len(tokens):
        if not (tokens[i].isdigit() or tokens[i] in ("oh", "o")):
            i += 1
            continue
        j = i
        while j < len(tokens) and (tokens[j].isdigit() or tokens[j] in ("oh", "o")):
            j += 1
        run = tokens[i:j]
        digits = sum(len(t) if t.isdigit() else 1 for t in run)
        if digits >= _OH_RUN_MIN_DIGITS and any(t.isdigit() for t in run):
            tokens[i:j] = ["0" if t in ("oh", "o") else t for t in run]
        i = j
    return " ".join(tokens)


_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), r)
    for p, r in (
        (r"\ba couple(?: of)?\b", "2"),
        (r"\bhalf past (\d{1,2})\b", r"\1:30"),
        (r"\bhalf (\d{1,2})\b(?! (?:people|persons|guests|pax))", r"\1:30"),
        (r"\bquarter past (\d{1,2})\b", r"\1:15"),
        (r"\b(\d{1,2}) o'?clock\b", r"\1:00"),
        (r"\bnoon\b", "12:00"),
        (r"\bmidnight\b", "00:00"),
        (r"\bdouble (\d)\b", r"\1\1"),
        (r"\btriple (\d)\b", r"\1\1\1"),
    )
)
_QUARTER_TO = re.compile(r"\bquarter to (\d{1,2})\b")


def convert_numbers(text: str) -> str:
    text = _words_to_digits(text)
    for pattern, repl in _PHRASES:
        text = pattern.sub(repl, text)
    text = _QUARTER_TO.sub(_quarter_to, text)
    return _fix_oh_runs(text)
