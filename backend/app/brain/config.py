"""Tunable thresholds and limits for the brain. No magic numbers elsewhere."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BrainConfig:
    intent_threshold: float = 0.5
    fuzzy_cutoff: int = 88
    fuzzy_min_len: int = 5
    fuzzy_confidence_penalty: float = 0.1
    max_nomatch: int = 3
    max_out_of_scope: int = 3
    max_silence: int = 2
    max_hold_silence: int = 3
    max_slot_attempts: int = 3
    max_verify_failures: int = 3
    honorific_every: int = 3
    alternatives_limit: int = 2
    alternatives_window_minutes: int = 120
    vague_time_options: int = 3
