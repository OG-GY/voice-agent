"""A caller who asks about the table types gets an explanation, not "I can't help with that"."""

from typing import Any

import pytest

from app.brain import Brain
from app.brain.types import Intent, SlotName


@pytest.mark.parametrize(
    "question",
    [
        "what's the difference",
        "what's there difference?",  # as heard in a real call
        "what is a window table",
        "what are private tables",
        "what kinds of tables do you have",
        "how are they different",
        "which one do you recommend",
    ],
)
def test_the_question_is_understood_as_a_seating_question(brain: Brain, talk: Any, question: str) -> None:
    result, _ = talk(brain, ["I want to book a table", question])
    assert result.trace.intent is Intent.FAQ_SEATING


def test_it_explains_the_three_table_types_and_asks_again(brain: Brain, talk: Any) -> None:
    result, replies = talk(brain, ["Can I book a table", "what's there difference?"])
    reply = replies[-1]
    assert "can't help" not in reply
    for word in ("regular table", "window table", "private family table"):
        assert word in reply
    assert "up to six" in reply and "up to four" in reply and "three to eight" in reply
    assert "Would you like a private family table" in reply or "Would you prefer a private table" in reply
    assert result.state.phase.value == "ask_seating"


def test_asking_about_a_table_type_does_not_choose_it(brain: Brain, talk: Any) -> None:
    result, _ = talk(brain, ["I want to book a table", "what is a private table"])
    assert not result.state.is_filled(SlotName.SEATING)


def test_the_booking_carries_on_after_the_explanation(brain: Brain, talk: Any) -> None:
    result, replies = talk(
        brain, ["I want to book a table", "what's the difference", "the window one"]
    )
    assert result.state.value(SlotName.SEATING).value == "window"
    assert "Which day" in replies[-1] or "What day" in replies[-1]


def test_it_also_works_before_a_booking_has_started(brain: Brain, talk: Any) -> None:
    result, replies = talk(brain, ["what's the difference between a window and a private table"])
    assert "private family table" in replies[-1]
    assert "Would you like me to book" in replies[-1]  # offered once, like any enquiry


def test_availability_questions_are_still_availability_questions(brain: Brain, talk: Any) -> None:
    result, _ = talk(brain, ["do you have any window tables tonight"])
    assert result.trace.intent is Intent.ASK_AVAILABILITY
