"""Chat with the brain in the terminal.

    uv run python -m app.brain.cli [--now "2026-10-30 18:00"] [--trace]
"""

import argparse
import logging
from datetime import date, datetime, time
from enum import Enum
from typing import Any

from app.brain import Brain, CallEvent, TurnResult
from app.brain.types import Trace
from app.services.booking import InMemoryBookingRepository
from app.services.clock import Clock, FixedClock, SystemClock
from app.services.restaurant import DEFAULT_RESTAURANT
from app.services.seed import seeded_repository

HELP = """commands:
  /state      show the call state          /bookings   list all bookings
  /silence    the caller says nothing      /hangup     the caller hangs up
  /reset      new call (same bookings)     /fresh      new call + fresh fake data
  /trace      toggle the decision trace    /quit       leave
"""
_TOP_INTENTS = 3


def _short(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime):
        return value.isoformat(timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.strftime("%H:%M")
    return str(value)


def format_trace(t: Trace) -> str:
    ranked = ", ".join(f"{i.value} {s:.2f}" for i, s in t.ranked_intents[:_TOP_INTENTS]) or "-"
    found = ", ".join(f"{e.type.value}={_short(e.value)} ({e.confidence:.2f})" for e in t.entities) or "-"
    changed = ", ".join(f"{c.slot.value}: {_short(c.old)} -> {_short(c.new)}" for c in t.slot_changes) or "-"
    fixes = ", ".join(f"{a}->{b}" for a, b, _ in t.fuzzy_fixes)
    lines = [
        f"    heard  : {t.normalized!r}" + (f"  (fuzzy: {fixes})" if fixes else ""),
        f"    intent : {t.intent.value} ({t.intent_score:.2f})   [{ranked}]",
        f"    found  : {found}",
        f"    changed: {changed}",
        f"    phase  : {t.phase_from.value} -> {t.phase_to.value}",
        f"    actions: {', '.join(a.type.value for a in t.actions) or '-'}",
        f"    why    : {t.reason}",
    ]
    return "\n".join(lines)


def format_state(result: TurnResult) -> str:
    s = result.state
    slots = ", ".join(f"{n.value}={_short(sl.value)}" for n, sl in s.slots.items() if sl.value is not None)
    pending = s.pending_question.type.value if s.pending_question else "-"
    return (
        f"    phase={s.phase.value} task={_short(s.task) if s.task else '-'} turn={s.turn}\n"
        f"    slots: {slots or '-'}\n"
        f"    expecting={_short(s.expected_slot) if s.expected_slot else '-'} pending={pending} "
        f"caller_title={_short(s.caller_title) if s.caller_title else '-'}"
    )


def format_bookings(repo: InMemoryBookingRepository) -> str:
    rows = [
        f"    {b.ref}  {b.date} {b.time:%H:%M}  {b.seating.value:<7} x{b.party}  {b.table_id:<5} "
        f"{b.name} [{b.status.value}]"
        for b in repo.bookings()
    ]
    return "\n".join(rows) or "    (none)"


def _build(clock: Clock) -> tuple[Brain, InMemoryBookingRepository]:
    repo = seeded_repository(DEFAULT_RESTAURANT, clock)
    return Brain(repo, clock), repo


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Chat with the Copper Pot receptionist brain.")
    parser.add_argument("--now", help='fix the current time, e.g. "2026-10-30 18:00"')
    parser.add_argument("--trace", action="store_true", help="show the decision trace each turn")
    parser.add_argument("--debug", action="store_true", help="show engine log lines")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.debug else logging.WARNING)

    clock: Clock = FixedClock(datetime.strptime(args.now, "%Y-%m-%d %H:%M")) if args.now else SystemClock()
    brain, repo = _build(clock)
    show_trace, calls = args.trace, 0

    def new_call() -> TurnResult:
        nonlocal calls
        calls += 1
        return brain.start(f"cli-{calls}")

    def show(result: TurnResult) -> None:
        print(f"bot> {result.reply or '(silent)'}")
        if show_trace:
            print(format_trace(result.trace))
        if result.ended:
            print("--- call ended ---\n")

    print(f"The Copper Pot receptionist. Now: {clock.now():%A %Y-%m-%d %H:%M}. Type /help for commands.")
    result = new_call()
    show(result)
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.startswith("/"):
            command = line.lower()
            if command in ("/quit", "/exit"):
                break
            if command == "/help":
                print(HELP)
            elif command == "/state":
                print(format_state(result))
            elif command == "/bookings":
                print(format_bookings(repo))
            elif command == "/trace":
                show_trace = not show_trace
                print(f"    trace {'on' if show_trace else 'off'}")
            elif command in ("/reset", "/fresh"):
                if command == "/fresh":
                    brain, repo = _build(clock)
                result = new_call()
                show(result)
            elif command in ("/silence", "/hangup"):
                event = CallEvent.SILENCE if command == "/silence" else CallEvent.HANGUP
                result = brain.handle_event(result.state, event)
                show(result)
            else:
                print("    unknown command, try /help")
            continue
        result = brain.handle(result.state, line)
        show(result)
        if result.ended:
            result = new_call()
            show(result)


if __name__ == "__main__":
    main()
