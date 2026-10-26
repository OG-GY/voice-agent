"""Dates: today, tomorrow, weekdays, "the 14th", "nov 3", "this weekend"."""

import re
from datetime import date, timedelta

from app.brain.nlu import lexicon
from app.brain.nlu.entities.base import ExtractContext, entity
from app.brain.types import DateOptions, Entity, SlotName

_MONTHS = "|".join(sorted(lexicon.MONTHS, key=len, reverse=True))
_WEEKDAYS = "|".join(lexicon.WEEKDAYS)

_AFTER_TOMORROW = re.compile(r"\bday after tomorrow\b")
_TOMORROW = re.compile(r"\btomorrow\b")
_TODAY = re.compile(r"\b(?:today|tonight)\b")
_WEEKDAY = re.compile(rf"\b(?:(next|this|on) )?({_WEEKDAYS})\b")
_ORDINAL = re.compile(rf"\b(?:the )?(\d{{1,2}})(?:st|nd|rd|th)(?: (?:of )?({_MONTHS}))?\b(?! one\b)")
_MONTH_FIRST = re.compile(rf"\b({_MONTHS}) (\d{{1,2}})(?:st|nd|rd|th)?\b(?![:\d])")
_DAY_OF_MONTH = re.compile(rf"\b(\d{{1,2}}) of ({_MONTHS})\b")
_WEEKEND = re.compile(r"\b(?:(this|next) )?weekend\b")
_NEXT_WEEK = re.compile(r"\bnext week\b")

_CONF_EXACT = 0.95
_CONF_ORDINAL = 0.9
_CONF_VAGUE = 0.7


def _next_weekday(today: date, weekday: int, include_today: bool) -> date:
    delta = (weekday - today.weekday()) % 7
    if delta == 0 and not include_today:
        delta = 7
    return today + timedelta(days=delta)


def _month_day(month: int, day: int, today: date) -> date | None:
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate
    return None


def _day_only(day: int, today: date) -> date | None:
    year, month = today.year, today.month
    for _ in range(2):
        try:
            candidate = date(year, month, day)
            if candidate >= today:
                return candidate
        except ValueError:
            pass
        month += 1
        if month == 13:
            month, year = 1, year + 1
    return None


def _weekend(today: date, upcoming: bool) -> list[date]:
    wd = today.weekday()
    saturday = today - timedelta(days=1) if wd == 6 else today + timedelta(days=5 - wd)
    if upcoming:
        saturday += timedelta(days=7)
    return [d for d in (saturday, saturday + timedelta(days=1)) if d >= today]


def extract_dates(text: str, ctx: ExtractContext) -> list[Entity]:
    today = ctx.today
    out: list[Entity] = []

    def add(m: re.Match[str], value: object, conf: float) -> None:
        out.append(entity(SlotName.DATE, value, m.span(), m.group(), conf))

    for m in _AFTER_TOMORROW.finditer(text):
        add(m, today + timedelta(days=2), _CONF_EXACT)
    for m in _TOMORROW.finditer(text):
        add(m, today + timedelta(days=1), _CONF_EXACT)
    for m in _TODAY.finditer(text):
        add(m, today, _CONF_EXACT)
    for m in _WEEKDAY.finditer(text):
        add(m, _next_weekday(today, lexicon.WEEKDAYS[m.group(2)], m.group(1) != "next"), _CONF_EXACT)
    for m in _MONTH_FIRST.finditer(text):
        found = _month_day(lexicon.MONTHS[m.group(1)], int(m.group(2)), today)
        if found:
            add(m, found, _CONF_EXACT)
    for m in _DAY_OF_MONTH.finditer(text):
        found = _month_day(lexicon.MONTHS[m.group(2)], int(m.group(1)), today)
        if found:
            add(m, found, _CONF_EXACT)
    for m in _ORDINAL.finditer(text):
        if ctx.choosing_option and not m.group(2):
            continue
        day = int(m.group(1))
        found = (
            _month_day(lexicon.MONTHS[m.group(2)], day, today)
            if m.group(2)
            else _day_only(day, today)
        )
        if found:
            add(m, found, _CONF_ORDINAL)
    for m in _WEEKEND.finditer(text):
        days = _weekend(today, upcoming=m.group(1) == "next")
        if days:
            add(m, DateOptions(dates=days, label="weekend"), _CONF_VAGUE)
    for m in _NEXT_WEEK.finditer(text):
        monday = today + timedelta(days=7 - today.weekday())
        days = [monday + timedelta(days=i) for i in range(1, 7)]
        add(m, DateOptions(dates=days, label="next week"), _CONF_VAGUE)
    return out
