"""Name, title and phone answers as real callers (and speech recognition) give them."""

from typing import Any

import pytest

from app.brain import Brain
from app.brain.types import SlotName, Title

BOOKING = "I want a general table saturday at 1 pm for 2 people"


def at_name_question(brain: Brain, talk: Any) -> Any:
    result, replies = talk(brain, [BOOKING])
    assert "name" in replies[-1].lower()  # availability was fine: the name is next
    return result


def at_title_question(brain: Brain, talk: Any) -> Any:
    result, replies = talk(brain, ["my name is Port"], at_name_question(brain, talk))
    assert "Mr., Mrs. or Ms. Port" in replies[-1]
    return result


def at_phone_question(brain: Brain, talk: Any) -> Any:
    result, replies = talk(brain, ["just the name"], at_title_question(brain, talk))
    assert "phone" in replies[-1].lower()
    return result


# -- the title question ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "Yes, the name is fine.",  # exactly what the caller said
        "the name is fine",
        "yes",
        "fine",
        "okay",
        "no",
        "just the name",
        "no title",
    ],
)
def test_agreeing_to_just_the_name_means_no_title_and_keeps_the_name(
    brain: Brain, talk: Any, answer: str
) -> None:
    result, replies = talk(brain, [answer], at_title_question(brain, talk))
    assert result.state.value(SlotName.NAME) == "Port"  # "Fine" must never become the name
    assert result.state.value(SlotName.TITLE) is Title.NONE
    assert "phone" in replies[-1].lower()


@pytest.mark.parametrize(("answer", "title"), [("Mister", Title.MR), ("Mrs", Title.MRS), ("Ms", Title.MS)])
def test_a_real_title_is_still_understood(brain: Brain, talk: Any, answer: str, title: Title) -> None:
    result, _ = talk(brain, [answer], at_title_question(brain, talk))
    assert result.state.value(SlotName.TITLE) is title
    assert result.state.value(SlotName.NAME) == "Port"


def test_a_misheard_title_is_asked_again_without_losing_the_name(brain: Brain, talk: Any) -> None:
    result, replies = talk(brain, ["Dad."], at_title_question(brain, talk))  # as heard in a real call
    assert "Mr., Mrs. or Ms. Port" in replies[-1]
    assert result.state.value(SlotName.NAME) == "Port"


# -- phone numbers --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spoken",
    [
        "0-3-0-0-1-2-3-4-5-6-7.",  # exactly what speech recognition wrote in a real call
        "0300 123 4567",
        "03001234567",
        "0300-123-4567",
        "zero three zero zero one two three four five six seven",
        "my number is 0300 123 4567",
    ],
)
def test_valid_phone_numbers_are_accepted_in_any_common_format(
    brain: Brain, talk: Any, spoken: str
) -> None:
    result, replies = talk(brain, [spoken], at_phone_question(brain, talk))
    assert result.state.phase.value == "confirm_booking", replies[-1]
    assert "0 3 0 0" in replies[-1]  # read back digit by digit


@pytest.mark.parametrize("wrong", ["031234567", "030012345678", "0300 123", "1234"])
def test_a_phone_number_of_the_wrong_length_is_called_out(brain: Brain, talk: Any, wrong: str) -> None:
    result, replies = talk(brain, [wrong], at_phone_question(brain, talk))
    reply = replies[-1]
    assert "doesn't look right" in reply and "10 or 11 digits" in reply
    assert "didn't catch" not in reply
    assert "phone number" in reply.lower()  # and it asks again
    assert not result.state.is_filled(SlotName.PHONE)
    assert not result.ended


def test_a_wrong_number_followed_by_a_right_one_works(brain: Brain, talk: Any) -> None:
    result, _ = talk(brain, ["031234567"], at_phone_question(brain, talk))
    result, _ = talk(brain, ["0-3-0-0-1-2-3-4-5-6-7"], result)
    assert result.state.phase.value == "confirm_booking"


def test_three_wrong_numbers_hand_the_caller_to_the_team(brain: Brain, talk: Any) -> None:
    result, replies = talk(brain, ["031234567", "031234567", "031234567"], at_phone_question(brain, talk))
    assert result.ended
    assert "member of our team" in replies[-1]


def test_words_that_are_not_digits_still_get_the_normal_reprompt(brain: Brain, talk: Any) -> None:
    _, replies = talk(brain, ["blah blah"], at_phone_question(brain, talk))
    assert "doesn't look right" not in replies[-1]
