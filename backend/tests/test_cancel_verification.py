"""Cancelling needs the booking reference AND the name; every mismatch looks the same."""

from typing import Any

import pytest
from helpers import FlakyRepository

from app.brain import Brain
from app.brain.types import SlotName
from app.services.booking import BookingStatus, InMemoryBookingRepository, VerifyLimits
from app.services.restaurant import DEFAULT_RESTAURANT
from app.services.seed import seeded_repository

# CP-1001 is the first fake booking: "Alex Sample", Friday window table.


def test_every_kind_of_mismatch_gets_the_same_reply(brain: Brain, talk: Any) -> None:
    _, wrong_name = talk(brain, ["cancel my booking", "CP 1 0 0 1", "Nobody Special"])
    _, unknown_ref = talk(brain, ["cancel my booking", "CP 9 9 9 9", "Alex Sample"])
    _, both_wrong = talk(brain, ["cancel my booking", "CP 9 9 9 9", "Nobody Special"])
    assert wrong_name[-1] == unknown_ref[-1] == both_wrong[-1]
    assert "couldn't match those details" in wrong_name[-1]


def test_a_mismatch_reveals_nothing_about_the_booking(brain: Brain, talk: Any) -> None:
    _, replies = talk(brain, ["cancel my booking", "CP 1 0 0 1", "Nobody Special"])
    reply = replies[-1].lower()
    for secret in ("alex", "sample", "window", "friday", "found", "exist"):
        assert secret not in reply


def test_matching_details_ask_for_confirmation_then_cancel(
    brain: Brain, repo: InMemoryBookingRepository, talk: Any
) -> None:
    result, replies = talk(brain, ["cancel my booking", "CP 1 0 0 1", "Alex Sample"])
    assert "Would you like me to cancel it" in replies[-1]
    result, replies = talk(brain, ["yes"], result)
    assert "has been cancelled" in replies[-1]
    booking = next(b for b in repo.bookings() if b.ref == "CP-1001")
    assert booking.status is BookingStatus.CANCELLED


@pytest.mark.parametrize("name", ["Alex Sample", "alex sample", "Sample", "Mr Sample"])
def test_full_name_or_surname_is_accepted(brain: Brain, talk: Any, name: str) -> None:
    _, replies = talk(brain, ["cancel my booking", "CP 1 0 0 1", name])
    assert "Would you like me to cancel it" in replies[-1]


def test_reference_and_name_in_one_sentence(brain: Brain, talk: Any) -> None:
    _, replies = talk(brain, ["cancel CP 1 0 0 1 under Alex Sample"])
    assert "Would you like me to cancel it" in replies[-1]


def test_failure_clears_both_answers_and_asks_again(brain: Brain, talk: Any) -> None:
    result, replies = talk(brain, ["cancel my booking", "CP 1 0 0 1", "Nobody Special"])
    assert "reference" in replies[-1]
    assert not result.state.is_filled(SlotName.BOOKING_REF)
    assert not result.state.is_filled(SlotName.NAME)


def test_third_failed_attempt_hands_off(brain: Brain, talk: Any) -> None:
    lines = ["cancel my booking"] + ["CP 9 9 9 9", "Nobody Special"] * 3
    result, replies = talk(brain, lines)
    assert result.ended
    assert "member of our team" in replies[-1]


def test_caller_limit_ends_the_call(clock: Any, talk: Any) -> None:
    repo = seeded_repository(DEFAULT_RESTAURANT, clock, VerifyLimits(per_caller=2))
    brain = Brain(repo, clock)
    lines = ["cancel my booking"] + ["CP 9 9 9 9", "Nobody Special"] * 3
    result, replies = talk(brain, lines)
    assert result.ended
    assert "try again later" in replies[-1]


def test_cancelled_booking_is_only_revealed_after_verification(brain: Brain, talk: Any) -> None:
    result, _ = talk(brain, ["cancel my booking", "CP 1 0 0 1", "Alex Sample", "yes"])
    result, replies = talk(brain, ["cancel my booking", "CP 1 0 0 1", "Nobody Special"], result)
    assert "already cancelled" not in replies[-1]
    result, replies = talk(brain, ["CP 1 0 0 1", "Alex Sample"], result)
    assert "already cancelled" in replies[-1]


def test_unavailable_storage_keeps_the_call_and_its_state(
    repo: InMemoryBookingRepository, clock: Any, talk: Any
) -> None:
    flaky = FlakyRepository(repo)
    brain = Brain(flaky, clock)  # type: ignore[arg-type]
    result, _ = talk(brain, ["I want a window table"])
    before = result.state
    flaky.down = True
    result, replies = talk(brain, ["friday at 8 pm for 2 people"], result)
    assert "isn't available right now" in replies[-1]
    assert not result.ended
    assert result.state.phase == before.phase
    assert result.state.slots == before.slots
    flaky.down = False
    result, replies = talk(brain, ["friday at 8 pm for 2 people"], result)
    assert "I do have" in replies[-1]  # Friday's window tables are full at 8 PM in the seed
