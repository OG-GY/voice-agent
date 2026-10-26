"""Contact details: booking reference, phone, title (Mr/Ms/sir/ma'am) and name."""

import re

from app.brain.nlu import lexicon
from app.brain.nlu.entities.base import ExtractContext, entity
from app.brain.types import Entity, SlotName, Title

_REF = re.compile(r"\bc ?p ?-? ?(\d(?: ?\d){3})\b")
_BARE_REF = re.compile(r"^(\d(?: ?\d){3})$")
# 10 or 11 digits, each optionally followed by one space or hyphen: "0300 123 4567",
# "0-3-0-0-1-2-3-4-5-6-7" (how speech recognition often writes digits read one by one).
_PHONE = re.compile(r"(?<![\d:])(\d(?:[ \-]?\d){9,10})(?![\d:])")
_PHONE_DIGITS = (10, 11)

_TITLE_WORD = re.compile(r"\b(" + "|".join(lexicon.TITLE_WORDS) + r")\b(?: ([a-z'\-]+))?")
_SELF_HONORIFIC = re.compile(
    r"\b(?:i'?m|i am|im|it'?s|its|it is|call me|this is) (?:a |an )?(sir|madam|ma'am|maam|mam)\b"
)
_BARE_HONORIFIC = re.compile(r"\b(sir|madam|ma'am|maam|mam)\b")
_NO_TITLE = re.compile(
    r"\b(?:just (?:the |my )?name|no title|name only|without (?:a )?title|"
    r"(?:the |my )?name(?: is|'s)? (?:fine|okay|ok|good|enough)|"
    r"(?:don't|do not|dont) (?:need|want|have) (?:a )?title)\b"
)
# Right after "Mr., Mrs. or Ms.?  Or just the name is fine.", a plain yes / no / fine means "no title".
_AGREES_NO_TITLE = re.compile(
    r"^(?:yes|yeah|yep|yup|sure|ok|okay|fine|alright|no|nope|none|any|"
    r"that's fine|that is fine|it's fine|it is fine)\b[\s,.!]*(?:please|thanks|thank you)?[\s.!]*$"
)

_NAME_WORD = r"[a-z][a-z'\-]*"
_TITLES = "|".join(lexicon.TITLE_WORDS)
_STRONG_NAME = re.compile(
    rf"\b(?:my name is|my name's|name is|name's|under|call me) (?:(?:{_TITLES}) )?"
    rf"({_NAME_WORD}(?: {_NAME_WORD})?)\b"
)
_WEAK_NAME = re.compile(
    rf"\b(?:this is|it's|its|i'm|i am|im|speaking) (?:({_TITLES}) )?"
    rf"({_NAME_WORD}(?: {_NAME_WORD})?)\b"
)
_MAX_BARE_NAME_WORDS = 3

_CONF_REF = 0.95
_CONF_PHONE = 0.9
_CONF_TITLE = 0.9
_CONF_HONORIFIC = 0.85
_CONF_NAME_STRONG = 0.9
_CONF_NAME_WEAK = 0.8
_CONF_NAME_BARE = 0.7


def extract_refs(text: str, ctx: ExtractContext) -> list[Entity]:
    out: list[Entity] = []
    for m in _REF.finditer(text):
        ref = "CP-" + m.group(1).replace(" ", "")
        out.append(entity(SlotName.BOOKING_REF, ref, m.span(), m.group(), _CONF_REF))
    if ctx.expected_slot == SlotName.BOOKING_REF and (bare := _BARE_REF.match(text)):
        ref = "CP-" + bare.group(1).replace(" ", "")
        out.append(entity(SlotName.BOOKING_REF, ref, bare.span(), bare.group(), 0.85))
    return out


def extract_phones(text: str, ctx: ExtractContext) -> list[Entity]:
    out: list[Entity] = []
    for m in _PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(1))
        if len(digits) in _PHONE_DIGITS:
            out.append(entity(SlotName.PHONE, digits, m.span(1), m.group(1), _CONF_PHONE))
    return out


def extract_titles(text: str, ctx: ExtractContext) -> list[Entity]:
    out: list[Entity] = []
    asked = ctx.expected_slot == SlotName.TITLE
    for m in _TITLE_WORD.finditer(text):
        follower = m.group(2)
        if asked or (follower and follower not in lexicon.NOT_NAMES):
            title = Title(lexicon.TITLE_WORDS[m.group(1)])
            out.append(entity(SlotName.TITLE, title, m.span(1), m.group(1), _CONF_TITLE))
    for m in _SELF_HONORIFIC.finditer(text):
        title = Title(lexicon.HONORIFIC_WORDS[m.group(1)])
        out.append(entity(SlotName.TITLE, title, m.span(1), m.group(1), _CONF_HONORIFIC))
    if asked:
        for m in _BARE_HONORIFIC.finditer(text):
            title = Title(lexicon.HONORIFIC_WORDS[m.group(1)])
            out.append(entity(SlotName.TITLE, title, m.span(1), m.group(1), _CONF_HONORIFIC))
    for m in _NO_TITLE.finditer(text):
        out.append(entity(SlotName.TITLE, Title.NONE, m.span(), m.group(), _CONF_TITLE))
    if asked and not out and (agreed := _AGREES_NO_TITLE.match(text)):
        out.append(entity(SlotName.TITLE, Title.NONE, agreed.span(), agreed.group(), _CONF_HONORIFIC))
    return out


def _clean_name(words: str, start: int) -> tuple[str, tuple[int, int]] | None:
    """Keep words up to the first non-name word; return (Title Cased name, span)."""
    kept: list[str] = []
    for word in words.split():
        if word in lexicon.NOT_NAMES:
            break
        kept.append(word)
    if not kept:
        return None
    joined = " ".join(kept)
    return joined.title(), (start, start + len(joined))


def extract_names(text: str, ctx: ExtractContext) -> list[Entity]:
    out: list[Entity] = []

    def add(found: tuple[str, tuple[int, int]] | None, conf: float) -> None:
        if found:
            out.append(entity(SlotName.NAME, found[0], found[1], text[found[1][0]:found[1][1]], conf))

    for m in _STRONG_NAME.finditer(text):
        add(_clean_name(m.group(1), m.start(1)), _CONF_NAME_STRONG)
    asked = ctx.expected_slot == SlotName.NAME
    for m in _WEAK_NAME.finditer(text):
        if asked or m.group(1):
            add(_clean_name(m.group(2), m.start(2)), _CONF_NAME_WEAK)
    if asked and not out:
        tokens = [t for t in text.split() if t not in lexicon.TITLE_WORDS]
        if 1 <= len(tokens) <= _MAX_BARE_NAME_WORDS and all(re.fullmatch(_NAME_WORD, t) for t in tokens):
            start = text.find(tokens[0])
            add(_clean_name(" ".join(tokens), start), _CONF_NAME_BARE)
    return out
