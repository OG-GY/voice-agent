"""Rule-based intent scoring: weighted patterns, context boosts and combination rules."""

import re
from dataclasses import dataclass, field

from app.brain.config import BrainConfig
from app.brain.nlu import lexicon
from app.brain.types import Entity, Intent, Phase, SlotName

_RULES: dict[Intent, tuple[tuple[re.Pattern[str], float], ...]] = {
    intent: tuple((re.compile(p), w) for p, w in rules)
    for intent, rules in lexicon.INTENT_PATTERNS.items()
}
_CORRECTION = re.compile(lexicon.CORRECTION_MARKER)
_EXPLICIT_QUESTION = re.compile(lexicon.EXPLICIT_QUESTION)
_QUESTION_START = re.compile(lexicon.QUESTION_START)

# Earlier = wins a tie on score.
_PRIORITY: tuple[Intent, ...] = (
    Intent.GOODBYE, Intent.ASK_HUMAN, Intent.RESTART, Intent.HOLD, Intent.CANCEL_BOOKING,
    Intent.CORRECT, Intent.BOOK, Intent.ASK_AVAILABILITY, Intent.FAQ_HOURS,
    Intent.FAQ_LOCATION, Intent.FAQ_SEATING, Intent.REPEAT, Intent.HELP, Intent.DECLINE,
    Intent.AFFIRM,
    Intent.DENY, Intent.THANKS, Intent.INFORM, Intent.OUT_OF_SCOPE, Intent.NOMATCH,
)
_RANK = {intent: i for i, intent in enumerate(_PRIORITY)}

_YES_NO_PHASES = {
    Phase.CONFIRM_BOOKING, Phase.CONFIRM_CANCEL, Phase.OFFER_BOOKING, Phase.OFFER_ALTERNATIVES,
}
_CONFIRM_PHASES = {Phase.CONFIRM_BOOKING, Phase.CONFIRM_CANCEL}
_CLOSING_PHASES = {
    Phase.BOOKED, Phase.CANCELLED, Phase.ANSWER_ENQUIRY, Phase.OFFER_BOOKING, Phase.END,
}
_POLITE_NOISE = {"thank you", "thanks"}
_CHANGEABLE = {
    SlotName.SEATING, SlotName.DATE, SlotName.TIME, SlotName.PARTY_SIZE,
    SlotName.NAME, SlotName.TITLE, SlotName.PHONE,
}
_YES_NO_BOOST = 0.2
_CORRECTION_WITH_ENTITY = 0.9
_CORRECTION_NO_ENTITY = 0.6
_INFORM_SCORE = 0.6
_GUESS_QUESTION_SCORE = 0.55
_RANKED_SHOWN = 5


@dataclass
class IntentResult:
    intent: Intent
    score: float
    ranked: list[tuple[Intent, float]] = field(default_factory=list)
    secondary: list[Intent] = field(default_factory=list)


def is_noise(text: str, phase: Phase | None) -> bool:
    """Empty text or a typical Whisper hallucination on silence."""
    if not text:
        return True
    if text in _POLITE_NOISE and phase in _CLOSING_PHASES:
        return False
    return text in lexicon.NOISE_PHRASES


def _raw_scores(text: str) -> dict[Intent, float]:
    scores: dict[Intent, float] = {}
    for intent, rules in _RULES.items():
        hits = [w for pattern, w in rules if pattern.search(text)]
        if hits:
            scores[intent] = max(hits)
    return scores


def classify(
    text: str,
    entities: list[Entity],
    phase: Phase | None,
    expected_slot: SlotName | None,
    config: BrainConfig,
) -> IntentResult:
    scores = _raw_scores(text)
    types = {e.type for e in entities}

    if Intent.GOODBYE in scores:
        # "no thanks, bye" is a goodbye, not just a refusal.
        scores.pop(Intent.DECLINE, None)
        scores.pop(Intent.DENY, None)
    if Intent.CANCEL_BOOKING in scores:
        scores.pop(Intent.BOOK, None)
    if Intent.ASK_AVAILABILITY in scores:
        # A question beats a booking request; an answer to our question is not a question.
        if _EXPLICIT_QUESTION.search(text):
            scores.pop(Intent.BOOK, None)
        elif expected_slot in types or Intent.BOOK in scores:
            scores.pop(Intent.ASK_AVAILABILITY)

    if _CORRECTION.search(text):
        if types & _CHANGEABLE:
            scores[Intent.CORRECT] = _CORRECTION_WITH_ENTITY
        elif phase in _CONFIRM_PHASES:
            scores[Intent.CORRECT] = _CORRECTION_NO_ENTITY

    if phase in _YES_NO_PHASES:
        for intent in (Intent.AFFIRM, Intent.DENY):
            if intent in scores:
                scores[intent] = min(1.0, scores[intent] + _YES_NO_BOOST)

    candidates = {i: s for i, s in scores.items() if s >= config.intent_threshold}
    if not candidates:
        if entities:
            candidates = {Intent.INFORM: _INFORM_SCORE}
        elif expected_slot is SlotName.PHONE and any(ch.isdigit() for ch in text):
            # Digits in answer to "your phone number?" that don't make a valid number: the
            # policy tells the caller the number looks wrong, instead of "didn't catch that".
            candidates = {Intent.INFORM: _INFORM_SCORE}
        elif _QUESTION_START.search(text):
            candidates = {Intent.OUT_OF_SCOPE: _GUESS_QUESTION_SCORE}
        else:
            return IntentResult(Intent.NOMATCH, 0.0)

    ranked = sorted(candidates.items(), key=lambda kv: (-kv[1], _RANK[kv[0]]))
    top, score = ranked[0]
    # "yes, but make it 8" / "no, 8pm" while confirming is a correction.
    if top in (Intent.AFFIRM, Intent.DENY) and phase in _CONFIRM_PHASES and types & _CHANGEABLE:
        top, score = Intent.CORRECT, _CORRECTION_WITH_ENTITY
    secondary: list[Intent] = [
        i
        for i, _ in ranked[1:]
        if i in (Intent.FAQ_HOURS, Intent.FAQ_LOCATION, Intent.FAQ_SEATING) and i != top
    ]
    return IntentResult(top, score, ranked[:_RANKED_SHOWN], secondary)
