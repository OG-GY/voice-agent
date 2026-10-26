"""NLU entry point: raw transcript -> NLUResult (normalized text, entities, intent)."""

from app.brain.config import BrainConfig
from app.brain.nlu.entities import extract_all
from app.brain.nlu.entities.base import ExtractContext
from app.brain.nlu.intents import classify, is_noise
from app.brain.nlu.normalizer import normalize
from app.brain.types import Entity, Intent, NLUResult, Phase


def _penalize_fuzzy(
    entities: list[Entity], fixes: list[tuple[str, str, int]], config: BrainConfig
) -> list[Entity]:
    """Entities built from a fuzzy-corrected word are less certain."""
    fixed_words = {fixed for _, fixed, _ in fixes}
    if not fixed_words:
        return entities
    return [
        e.model_copy(update={"confidence": max(0.0, e.confidence - config.fuzzy_confidence_penalty)})
        if fixed_words & set(e.text.split())
        else e
        for e in entities
    ]


def run_nlu(
    raw: str, ctx: ExtractContext, config: BrainConfig, phase: Phase | None = None
) -> NLUResult:
    norm = normalize(raw, config, ctx.expected_slot)
    if is_noise(norm.text, phase):
        return NLUResult(
            raw=raw, normalized=norm.text, intent=Intent.NOMATCH, intent_score=0.0,
            fuzzy_fixes=norm.fixes, is_noise=True,
        )
    entities = _penalize_fuzzy(extract_all(norm.text, ctx), norm.fixes, config)
    result = classify(norm.text, entities, phase, ctx.expected_slot, config)
    return NLUResult(
        raw=raw,
        normalized=norm.text,
        intent=result.intent,
        intent_score=result.score,
        secondary_intents=result.secondary,
        ranked=result.ranked,
        entities=entities,
        fuzzy_fixes=norm.fixes,
    )
