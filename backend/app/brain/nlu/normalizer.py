"""Clean raw speech-to-text output into a predictable form for the NLU."""

import re
import unicodedata
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from app.brain.config import BrainConfig
from app.brain.nlu import lexicon
from app.brain.nlu.numbers import convert_numbers
from app.brain.types import SlotName

_FILLER_RE = re.compile(r"\b(?:" + "|".join(lexicon.FILLERS) + r")\b")
_DOTTED_AMPM = re.compile(r"\b([ap])\.m\.?")
_DECIMAL_TIME = re.compile(r"(\d)\.(\d)")
_PUNCT = re.compile(r"[^a-z0-9:'\-\s]")
_FUZZY_MAX_LEN_DIFF = 2


@dataclass
class NormalizeResult:
    text: str
    fixes: list[tuple[str, str, int]] = field(default_factory=list)


def _basic_clean(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw).lower()
    text = text.replace("’", "'").replace("‘", "'").replace("`", "'")
    text = _DOTTED_AMPM.sub(r"\1m", text)
    text = _DECIMAL_TIME.sub(r"\1:\2", text)
    text = _PUNCT.sub(" ", text)
    tokens = (t.strip("'-") for t in text.split())
    return " ".join(t for t in tokens if t)


def _fuzzy_fix(
    text: str, config: BrainConfig, expected_slot: SlotName | None
) -> tuple[str, list[tuple[str, str, int]]]:
    # Names are not typos: never "correct" them.
    if expected_slot == SlotName.NAME:
        return text, []
    out: list[str] = []
    fixes: list[tuple[str, str, int]] = []
    for tok in text.split():
        if (
            len(tok) < config.fuzzy_min_len
            or not tok.isalpha()
            or tok in lexicon.PROTECTED
            or tok in lexicon.VOCAB_SET
            or tok in lexicon.KNOWN_WORDS
        ):
            out.append(tok)
            continue
        match = process.extractOne(
            tok, lexicon.VOCAB, scorer=fuzz.ratio, score_cutoff=config.fuzzy_cutoff
        )
        if (
            match
            and match[0][0] == tok[0]
            and abs(len(match[0]) - len(tok)) <= _FUZZY_MAX_LEN_DIFF
        ):
            out.append(match[0])
            fixes.append((tok, match[0], int(match[1])))
        else:
            out.append(tok)
    return " ".join(out), fixes


def normalize(
    raw: str, config: BrainConfig, expected_slot: SlotName | None = None
) -> NormalizeResult:
    text = _basic_clean(raw)
    text = _FILLER_RE.sub(" ", text)
    for pattern, repl in lexicon.MISHEARINGS:
        text = pattern.sub(repl, text)
    text = convert_numbers(" ".join(text.split()))
    text, fixes = _fuzzy_fix(text, config, expected_slot)
    return NormalizeResult(text=" ".join(text.split()), fixes=fixes)
