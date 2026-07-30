"""Shared Parser V2 text/table helpers."""

# ruff: noqa: RUF001

from __future__ import annotations

import re
from datetime import date

from tbm_twin.geology.document_models import PdfPageText

CHAINAGE_RE = r"(?:DyK|DK|K)\s*\d+\s*\+\s*\d+(?:\.\d+)?"
RANGE_RE = re.compile(
    rf"(?P<start>{CHAINAGE_RE})\s*(?:~|\uff5e|—|--|-|至)\s*(?P<end>{CHAINAGE_RE})",
    re.IGNORECASE,
)


def compact(text: str) -> str:
    """Remove whitespace and normalize common range separators."""

    return re.sub(r"\s+", "", text).replace("\uff5e", "~")


def chainage_to_float(raw: str) -> float:
    """Convert DyK1013+184.2-like text to absolute chainage metres."""

    match = re.search(r"(\d+)\s*\+\s*(\d+(?:\.\d+)?)", raw)
    if not match:
        msg = f"Invalid chainage: {raw}"
        raise ValueError(msg)
    return float(match.group(1)) * 1000 + float(match.group(2))


def parse_range(raw: str) -> tuple[float, float, str]:
    """Parse the first chainage interval in text."""

    match = RANGE_RE.search(raw)
    if not match:
        msg = f"Invalid chainage range: {raw}"
        raise ValueError(msg)
    return (
        chainage_to_float(match.group("start")),
        chainage_to_float(match.group("end")),
        match.group(0),
    )


def parse_first_chainage(raw: str) -> float | None:
    """Parse the first chainage point in text."""

    match = re.search(CHAINAGE_RE, raw, flags=re.IGNORECASE)
    return chainage_to_float(match.group(0)) if match else None


def all_text(pages: list[PdfPageText]) -> str:
    """Join page text with page breaks."""

    return "\n".join(page.page_text for page in pages)


def find_page(pages: list[PdfPageText], token: str) -> PdfPageText:
    """Find first page containing token."""

    for page in pages:
        if token in page.page_text:
            return page
    return pages[0]


def arabic_date(text: str) -> date | None:
    """Extract the first Arabic date from text."""

    match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


_CHINESE_DIGITS = {
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


def chinese_date(text: str) -> date | None:
    """Extract a Chinese numeral date such as 二〇二三年九月十四日."""

    match = re.search(
        r"(二[\u3007〇零一二三四五六七八九]{3})年"
        r"([一二三四五六七八九十]+)月"
        r"([一二三四五六七八九十]+)日",
        text,
    )
    if not match:
        return None
    year = int("".join(str(_CHINESE_DIGITS[ch]) for ch in match.group(1)))
    return date(year, _chinese_number(match.group(2)), _chinese_number(match.group(3)))


def _chinese_number(text: str) -> int:
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + _CHINESE_DIGITS[text[1]]
    if text.endswith("十"):
        return _CHINESE_DIGITS[text[0]] * 10
    if "十" in text:
        left, right = text.split("十", 1)
        return _CHINESE_DIGITS[left] * 10 + _CHINESE_DIGITS[right]
    return _CHINESE_DIGITS[text]


def format_chainage(value: float) -> str:
    """Format chainage for stable IDs and artifacts."""

    return str(value).rstrip("0").rstrip(".")
