from datetime import timedelta

import pytest

from cctop.duration import parse_duration


def test_parse_zero() -> None:
    assert parse_duration("0") == timedelta(0)


def test_parse_minutes() -> None:
    assert parse_duration("30m") == timedelta(minutes=30)


def test_parse_hours() -> None:
    assert parse_duration("2h") == timedelta(hours=2)


def test_parse_days() -> None:
    assert parse_duration("1d") == timedelta(days=1)


def test_parse_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration("abc")


def test_parse_empty_raises() -> None:
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration("")
