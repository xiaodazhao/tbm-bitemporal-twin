# ruff: noqa: RUF001
"""Shared text and chainage helpers for table parser V2."""

from __future__ import annotations

import re
from collections.abc import Iterable

CHAINAGE_RE = re.compile(
    r"(?:D\s*y\s*K|D\s*K|K)?\s*(\d{4})\s*\+\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
CHAINAGE_TOKEN = r"(?:D\s*y\s*K|D\s*K|K)?\s*(\d{4})\s*\+\s*(\d+(?:\.\d+)?)"
DIRECT_INTERVAL_RE = re.compile(
    rf"({CHAINAGE_TOKEN})\s*[~～—－-]\s*({CHAINAGE_TOKEN})",
    re.IGNORECASE,
)
PLUS_RE = re.compile(r"\+\s*(\d+(?:\.\d+)?)")
RANGE_SEP_RE = re.compile(r"[~～—－-]")
NUMERIC_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")
CHINESE_DATE_RE = re.compile(
    r"([〇零一二三四五六七八九十]{4})年([〇零一二三四五六七八九十]+)月([〇零一二三四五六七八九十]+)日"
)


def normalize_text(value: object) -> str:
    """Normalize whitespace without changing domain words."""

    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()


def compact_text(value: object) -> str:
    """Remove whitespace for robust Chinese label matching."""

    return re.sub(r"\s+", "", normalize_text(value))


def parse_chainage_value(text: str) -> float | None:
    """Parse the first full chainage expression into absolute metres."""

    match = CHAINAGE_RE.search(text)
    if not match:
        return None
    return float(match.group(1)) * 1000.0 + float(match.group(2))


def parse_chainage_interval(text: str) -> tuple[float, float] | None:
    """Parse the first full chainage interval in absolute metres."""

    intervals = parse_all_chainage_intervals(text)
    if not intervals:
        return None
    return intervals[0][1], intervals[0][2]


def raw_chainage_interval(text: str) -> str:
    """Return the source expression for the first full interval."""

    intervals = parse_all_chainage_intervals(text)
    return intervals[0][0] if intervals else normalize_text(text)


def parse_all_chainage_intervals(text: str) -> list[tuple[str, float, float]]:
    """Parse all explicit intervals in a text block."""

    intervals: list[tuple[str, float, float]] = []
    for match in DIRECT_INTERVAL_RE.finditer(text):
        raw = normalize_text(match.group(0))
        start = float(match.group(2)) * 1000.0 + float(match.group(3))
        end = float(match.group(5)) * 1000.0 + float(match.group(6))
        intervals.append((raw, start, end))
    return intervals


def complete_plus_chainage(token: str, start: float, end: float) -> float | None:
    """Complete a ``+NNN`` risk point from the row interval."""

    match = PLUS_RE.search(token)
    if not match:
        return None
    metres = float(match.group(1))
    start_km = int(start // 1000)
    end_km = int(end // 1000)
    candidates = [km * 1000.0 + metres for km in range(start_km, end_km + 1)]
    inside = [value for value in candidates if min(start, end) - 1 <= value <= max(start, end) + 1]
    if inside:
        return inside[0]
    return min(candidates, key=lambda value: min(abs(value - start), abs(value - end)))


def first_match(candidates: Iterable[str], text: str) -> str | None:
    """Return the longest candidate contained in text."""

    compact = compact_text(text)
    for candidate in sorted(candidates, key=len, reverse=True):
        if compact_text(candidate) in compact:
            return candidate
    return None


def parse_local_dates(text: str) -> list[str]:
    """Parse numeric and Chinese local dates from text."""

    ordered: list[tuple[int, str]] = []
    for match in NUMERIC_DATE_RE.finditer(text):
        ordered.append(
            (
                match.start(),
                f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}",
            )
        )
    for match in CHINESE_DATE_RE.finditer(text):
        year = "".join(str(_chinese_digit(char)) for char in match.group(1))
        month = _chinese_number(match.group(2))
        day = _chinese_number(match.group(3))
        if month is not None and day is not None:
            ordered.append((match.start(), f"{int(year):04d}-{month:02d}-{day:02d}"))
    return [date for _, date in sorted(ordered)]


def first_local_date(text: str) -> str | None:
    """Return the first local date in text."""

    dates = parse_local_dates(text)
    return dates[0] if dates else None


def parse_submitted_local_date(text: str, reference_date: str | None) -> str | None:
    """Parse explicit submitted-time expressions using a known reference year."""

    year = int(reference_date[:4]) if reference_date else None
    full_match = re.search(
        r"提交日期[:：]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        text,
    )
    if full_match:
        return (
            f"{int(full_match.group(1)):04d}-"
            f"{int(full_match.group(2)):02d}-{int(full_match.group(3)):02d}"
        )
    compact = compact_text(text)
    month_day = re.search(
        r"(?:并于|于)(\d{1,2})月(\d{1,2})日提交(?:了)?预报结果",
        compact,
    )
    if month_day and year is not None:
        return f"{year:04d}-{int(month_day.group(1)):02d}-{int(month_day.group(2)):02d}"
    return None


def _chinese_digit(char: str) -> int:
    digits = {
        "〇": 0,
        "零": 0,
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    return digits[char]


def _chinese_number(text: str) -> int | None:
    digits = {
        "〇": 0,
        "零": 0,
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if text in digits:
        return digits[text]
    if text == "十":
        return 10
    if text.startswith("十"):
        tail = text[1:]
        return 10 + digits.get(tail, 0)
    if "十" in text:
        left, right = text.split("十", maxsplit=1)
        return digits.get(left, 0) * 10 + digits.get(right, 0)
    if all(char in digits for char in text):
        return int("".join(str(digits[char]) for char in text))
    return None
