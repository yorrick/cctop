import re
from datetime import timedelta

_DURATION_RE = re.compile(r"^(\d+)([mhd])$")


def parse_duration(value: str) -> timedelta:
    """Parse a duration string like '30m', '2h', '1d' into a timedelta.

    '0' means zero duration.
    """
    if value == "0":
        return timedelta(0)

    match = _DURATION_RE.match(value.strip())
    if not match:
        raise ValueError(f"Invalid duration: {value!r}. Use format like 30m, 2h, 1d, or 0.")

    amount = int(match.group(1))
    unit = match.group(2)

    match unit:
        case "m":
            return timedelta(minutes=amount)
        case "h":
            return timedelta(hours=amount)
        case "d":
            return timedelta(days=amount)
        case _:
            raise ValueError(f"Invalid duration unit: {unit!r}")
