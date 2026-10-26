"""Keyword lists and word maps used by the NLU. Keep all vocabulary here."""

import re
from datetime import time

from app.brain.types import Intent
from app.services.restaurant import Seating

FILLERS: tuple[str, ...] = (
    "you know", "umm", "um", "uhh", "uh", "erm", "er", "hmmm", "hmm", "mm", "ah",
)

# (pattern, replacement) applied to lower-cased text with punctuation already stripped.
MISHEARINGS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), r)
    for p, r in (
        (r"\bfor (people|persons|guests|pax)\b", r"four \1"),
        (r"\b(?:to|too|tu) (people|persons|guests|pax)\b", r"two \1"),
        (r"\b(a|the|your|any|private|window) (?:cable|stable|tibble)\b", r"\1 table"),
        (r"(\d) ?([ap]) ?m\b", r"\1\2m"),
    )
)

# Words the fuzzy corrector may correct *toward*. Never put protected words here.
VOCAB: tuple[str, ...] = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december",
    "tomorrow", "tonight", "today", "weekend", "evening", "afternoon", "lunch", "dinner",
    "window", "private", "general", "family", "booth", "quiet",
    "table", "tables", "booking", "reservation", "people", "persons", "guests",
    "address", "location", "timings", "opening", "available", "availability",
    "manager", "human",
)
VOCAB_SET: frozenset[str] = frozenset(VOCAB)

# Never changed by the fuzzy corrector, and never corrected into.
PROTECTED: frozenset[str] = frozenset({
    "yes", "yeah", "yep", "no", "nope", "not", "cancel", "book", "sure", "okay", "ok",
    "wait", "stop", "hold", "bye", "goodbye", "repeat", "again", "human", "agent",
})

# Real words that sit close to VOCAB entries; leave them alone.
KNOWN_WORDS: frozenset[str] = frozenset({
    "privacy", "windows", "person", "guest", "booked", "bookings", "minute", "minutes",
    "before", "after", "there", "their", "would", "could", "should", "please", "thanks",
    "thank", "about", "sorry", "anyone", "closed", "hours", "other", "which", "where",
    "later", "earlier", "around", "between", "during", "always", "never", "family's",
    "quieter", "tables", "dinners", "lunches", "evenings", "weekends", "mondays",
    "fridays", "saturdays", "sundays", "tuesdays", "thursdays", "wednesdays",
})

# Whisper tends to hallucinate these on silence or noise.
NOISE_PHRASES: frozenset[str] = frozenset({
    "you", "thank you", "thanks", "thanks for watching", "thank you for watching",
    "the end", "subtitles by", "mm", "hmm", "uh", "um",
})

WEEKDAYS: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
    "saturday": 5, "sunday": 6,
}
MONTHS: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Vague times of day -> (start, end).
TIME_RANGES: dict[str, tuple[time, time]] = {
    "lunch": (time(12, 0), time(15, 0)),
    "afternoon": (time(15, 0), time(18, 0)),
    "evening": (time(18, 0), time(21, 0)),
    "dinner": (time(18, 0), time(21, 0)),
    "tonight": (time(18, 0), time(21, 0)),
}

SEATING_PHRASES: dict[Seating, tuple[str, ...]] = {
    Seating.WINDOW: (
        "window side", "window seat", "by the window", "next to the window", "window", "view",
    ),
    Seating.PRIVATE: (
        "private room", "private", "privacy", "family table", "family booth", "booth",
        "quiet", "separate", "secluded",
    ),
    Seating.GENERAL: ("general", "normal", "regular", "standard", "main dining", "main hall"),
}
# "I don't care which table" -> general. The second set is only trusted right after we ask.
INDIFFERENT_ALWAYS: tuple[str, ...] = (
    "doesn't matter", "does not matter", "no preference", "don't mind", "dont mind",
    "whatever is free", "whatever's free", "anything is fine", "any is fine",
    "any table is fine", "up to you",
)
INDIFFERENT_WHEN_ASKED: tuple[str, ...] = (
    "any table", "any", "anywhere", "whatever", "either", "anything",
)

TITLE_WORDS: dict[str, str] = {
    "mr": "mr", "mister": "mr", "mrs": "mrs", "missus": "mrs", "ms": "ms",
    "miss": "miss", "mx": "mx",
}
HONORIFIC_WORDS: dict[str, str] = {
    "sir": "mr", "madam": "ms", "ma'am": "ms", "maam": "ms", "mam": "ms",
}

# Words that can never be part of a person's name.
NOT_NAMES: frozenset[str] = frozenset({
    "yes", "yeah", "yep", "no", "nope", "ok", "okay", "sure", "please", "thanks", "thank",
    "hello", "hi", "hey", "sorry", "and", "the", "a", "an", "for", "at", "on", "in", "to",
    "of", "i", "me", "my", "we", "you", "it", "its", "is", "am", "are", "was", "that", "this",
    "just", "also", "with", "from", "but", "so", "not", "do", "can", "could", "would",
    "want", "like", "need", "book", "booking", "cancel", "table", "tables", "window",
    "private", "general", "people", "persons", "guests", "tonight", "tomorrow", "today",
    "actually", "wait", "hold", "have", "has", "looking", "calling", "wondering", "name",
    "then", "now", "um", "uh", "your", "our", "there", "here", "what", "when", "where",
    "pm", "reservation", "party", "family", "mr", "mister", "mrs", "missus", "ms",
    "miss", "mx", "sir", "madam", "ma'am", "maam", "under", "by", "as", "or", "if",
    "fine", "good", "great", "enough", "alright", "right", "correct",
}) | frozenset(WEEKDAYS) | frozenset(MONTHS)

# Intent patterns on normalized text: (regex, weight). Numbers are already digits, so
# "one second" arrives as "1 second".
INTENT_PATTERNS: dict[Intent, tuple[tuple[str, float], ...]] = {
    Intent.BOOK: (
        (r"\b(?:book|reserve)\b", 0.8),
        (r"\b(?:i|we)(?:'d| would| want| need| wanna)(?: like| love)?(?: to)?(?: get| have| make)?"
         r"(?: a| the)? (?:table|reservation|booking)\b", 0.85),
        (r"\b(?:make|need|want) (?:a |the )?(?:reservation|booking)\b", 0.85),
        (r"\btable for\b", 0.6),
        (r"\breservation\b", 0.5),
    ),
    Intent.ASK_AVAILABILITY: (
        (r"\b(?:do|does) you (?:have|got)\b.*\b(?:tables?|space|room|availability|free|seats?)\b",
         0.85),
        (r"\b(?:any|are there|is there)\b.*\b(?:tables?|availability|space|room|slots?|seats?)\b",
         0.8),
        (r"\bavailab(?:le|ility)\b", 0.75),
        (r"\b(?:are|is) you (?:busy|full|booked|fully booked)\b", 0.75),
    ),
    Intent.CANCEL_BOOKING: (
        (r"\bcancel\b", 0.9),
        (r"\b(?:call off|drop) (?:my|the|our) (?:booking|reservation)\b", 0.85),
    ),
    Intent.AFFIRM: (
        (r"\b(?:yes|yeah|yep|yup|sure|correct|exactly|definitely|absolutely|perfect|"
         r"sounds good|go ahead|that'?s right|that'?s correct|that works|of course|alright|"
         r"okay|ok)\b", 0.8),
    ),
    Intent.DENY: (
        (r"\b(?:no|nope|nah|not really|incorrect|wrong)\b", 0.8),
        (r"\bthat'?s (?:not right|wrong|incorrect)\b", 0.85),
    ),
    Intent.DECLINE: (
        (r"\b(?:no thanks|no thank you|not now|not today|never ?mind|i'?ll call back|"
         r"call back later|maybe later|that'?s all i needed|just wanted to know|"
         r"just wanted to ask)\b", 0.95),
        (r"\bjust (?:checking|asking|wondering|curious|enquiring|inquiring)\b", 0.9),
    ),
    Intent.FAQ_HOURS: (
        (r"\b(?:timings|opening hours|opening times|working hours|business hours|your hours|"
         r"what time (?:do|are) you (?:open|close)|when (?:do|are) you (?:open|close)|"
         r"are you open|do you open|what time (?:do you )?(?:open|close)|when do you close|"
         r"until when|how late)\b", 0.9),
        (r"\b(?:open|opens|close|closes|closing|opening)\b", 0.5),
    ),
    Intent.FAQ_SEATING: (
        (r"\bdifferen(?:ce|t|ces)\b", 0.9),
        (r"\bwhat(?:'s| is| are| does)\b(?: a| an| the)? (?:private|window|general|regular)\b", 0.9),
        (r"\b(?:types?|kinds?|options?) of (?:tables?|seating|seats)\b", 0.85),
        (r"\bwhat (?:types|kinds|options)\b", 0.8),
        (r"\bwhich (?:one )?(?:is better|would be better|do you recommend|do you suggest|should i)\b", 0.8),
        (r"\bhow (?:are|is) (?:they|those|these|the tables|the seating|the options) different\b", 0.85),
        (r"\bexplain\b.*\b(?:tables?|seating|private|window|options)\b", 0.8),
    ),
    Intent.FAQ_LOCATION: (
        (r"\b(?:where (?:are|is) you|where'?s (?:the|your) (?:restaurant|place)|address|"
         r"location|located|how (?:do|can) i (?:get|find)|directions?|which area|"
         r"what street)\b", 0.9),
    ),
    Intent.REPEAT: (
        (r"\b(?:repeat|say that again|say again|come again|pardon|what was that|"
         r"what did you say|(?:1|one) more time|didn'?t (?:catch|hear|get) that|"
         r"i didn'?t catch)\b", 0.9),
        (r"^(?:what|sorry|pardon|huh|eh)$", 0.8),
    ),
    Intent.HELP: (
        (r"\b(?:what can you do|how does this work|help|what do you do|what services|"
         r"what can i do)\b", 0.85),
    ),
    Intent.RESTART: (
        (r"\b(?:start over|start again|restart|begin again|from the beginning|from scratch|"
         r"reset)\b", 0.9),
    ),
    Intent.ASK_HUMAN: (
        (r"\b(?:speak|talk) to (?:a |an |the )?(?:person|human|manager|agent|staff|someone|"
         r"somebody|operator|real person)\b", 0.95),
        (r"\b(?:human|manager|operator|real person|representative|customer service)\b", 0.85),
    ),
    Intent.HOLD: (
        (r"\b(?:hold on|hold the line|(?:1|one) (?:sec|second|moment|minute)|"
         r"just a (?:sec|second|moment|minute)|wait a (?:sec|second|moment|minute)|"
         r"give me a (?:sec|second|moment|minute)|let me (?:check|think|see|ask)|hang on|"
         r"bear with me|hang tight)\b", 0.9),
        (r"^wait$", 0.8),
    ),
    Intent.GOODBYE: (
        (r"\b(?:bye|goodbye|good bye|see you|take care|that'?s all|that is all|that'?s it|"
         r"talk later|have a good (?:day|one|evening)|hang up|gotta go|i have to go|"
         r"got to go)\b", 0.9),
    ),
    Intent.THANKS: (
        (r"\b(?:thanks|thank you|thank u|cheers|much appreciated|appreciate it)\b", 0.8),
    ),
    Intent.OUT_OF_SCOPE: (
        (r"\b(?:menu|food|vegan|vegetarian|gluten|allergy|allergies|allergic|halal|kosher|"
         r"price|prices|cost|how much|parking|weather|news|joke|music|delivery|deliver|"
         r"takeaway|takeout|job|jobs|hiring|career|wifi|dress code|chef|score|football|"
         r"politics|president|capital of|who is|who was|tell me about|translate|"
         r"calculate)\b", 0.75),
    ),
}

CORRECTION_MARKER = (
    r"\b(?:actually|make it|change (?:it )?to|change that|instead|no wait|sorry i meant|"
    r"i meant|rather|switch to|move it to|let'?s make it)\b"
)
# Explicit question phrasing: keeps "do you have a window table" a question even mid-booking.
EXPLICIT_QUESTION = r"\b(?:(?:do|does) you (?:have|got)|are there|is there|have you got)\b"
QUESTION_START = r"^(?:what|who|why|how|when|where|which|can you|could you|do you|are you|is it)\b"
