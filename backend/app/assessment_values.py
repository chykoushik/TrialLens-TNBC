import operator
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction

COMPARATORS = {
    "==": operator.eq, "!=": operator.ne, "<": operator.lt,
    "<=": operator.le, ">": operator.gt, ">=": operator.ge,
}
UNITS = {
    "%": ("percentage", Decimal(1)),
    "fraction": ("percentage", Decimal(100)),
    "1": ("dimensionless", Decimal(1)),
    "ECOG": ("ECOG", Decimal(1)),
    "CPS": ("CPS", Decimal(1)),
    "TPS": ("TPS", Decimal(1)),
    "mg/dL": ("mass_concentration", Decimal("0.01")),
    "g/L": ("mass_concentration", Decimal(1)),
    "g/dL": ("mass_concentration", Decimal(10)),
    "mg/L": ("mass_concentration", Decimal("0.001")),
    "days": ("time", Decimal(86400)),
    "hours": ("time", Decimal(3600)),
    "weeks": ("time", Decimal(604800)),
}


def number(value: Decimal | str | None) -> Decimal:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite numeric value")
        return value
    if value is None or not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", str(value)):
        raise ValueError("Unsupported numeric value")
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ValueError("Unsupported numeric value") from None
    if not result.is_finite():
        raise ValueError("Non-finite numeric value")
    return result


def converted(value: Decimal | str | None, units: str | None, target: str) -> Fraction:
    if units not in UNITS or target not in UNITS or UNITS[units][0] != UNITS[target][0]:
        raise ValueError("Incompatible or unsupported units")
    return Fraction(number(value)) * Fraction(UNITS[units][1])


def seconds(delta: timedelta) -> Fraction:
    return Fraction((delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds, 1000000)
