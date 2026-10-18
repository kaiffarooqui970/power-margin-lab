"""German baseload power futures: delivery periods, delivery hours, trading calendar.

Delivery hours are computed as the UTC difference between delivery start and end (Europe/Berlin
local midnight), so DST months come out right: March 743 h, October 745 h. Subtracting two aware
datetimes that share one ZoneInfo would give wall-clock time and is deliberately avoided.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")

ECC_CODE = {"M": "DEBM", "Q": "DEBQ", "Y": "DEBY"}
DELIVERY_TYPE_FROM_CODE = {v: k for k, v in ECC_CODE.items()}


def _berlin_midnight_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=BERLIN).astimezone(UTC)


def delivery_hours(start: date, end_inclusive: date) -> int:
    """Number of delivery hours from local midnight of `start` to local midnight after `end`."""
    seconds = (_berlin_midnight_utc(end_inclusive + timedelta(days=1))
               - _berlin_midnight_utc(start)).total_seconds()
    return round(seconds / 3600)


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    return date(d.year + m // 12, m % 12 + 1, 1)


@dataclass(frozen=True, order=True)
class Product:
    """A German baseload futures contract identified by its delivery period."""

    delivery_start: date
    delivery_type: str  # "M" | "Q" | "Y"

    def __post_init__(self) -> None:
        if self.delivery_type not in ECC_CODE:
            raise ValueError(f"unknown delivery type {self.delivery_type!r}")
        s = self.delivery_start
        if s.day != 1 or (self.delivery_type == "Q" and s.month not in (1, 4, 7, 10)) or (
            self.delivery_type == "Y" and s.month != 1
        ):
            raise ValueError(f"invalid delivery start {s} for type {self.delivery_type}")

    @property
    def n_months(self) -> int:
        return {"M": 1, "Q": 3, "Y": 12}[self.delivery_type]

    @property
    def delivery_end(self) -> date:
        return _add_months(self.delivery_start, self.n_months) - timedelta(days=1)

    @property
    def delivery_hours(self) -> int:
        return delivery_hours(self.delivery_start, self.delivery_end)

    @property
    def ecc_code(self) -> str:
        return ECC_CODE[self.delivery_type]

    @property
    def product_id(self) -> str:
        s = self.delivery_start
        if self.delivery_type == "M":
            return f"DEBM-{s:%Y-%m}"
        if self.delivery_type == "Q":
            return f"DEBQ-{s.year}-Q{(s.month - 1) // 3 + 1}"
        return f"DEBY-{s.year}"

    def contains(self, other: Product) -> bool:
        """True if `other`'s delivery period lies inside this one (month inside quarter)."""
        return (self.delivery_start <= other.delivery_start
                and other.delivery_end <= self.delivery_end and self != other)

    def months(self) -> list[Product]:
        return [Product(_add_months(self.delivery_start, i), "M") for i in range(self.n_months)]

    @classmethod
    def from_ecc(cls, code: str, expiry_year: int, expiry_month: int) -> Product:
        """ECC files key contracts by product code + year/month of delivery start (checked against
        fDeliv in the SPAN XML, 2026-10-16)."""
        return cls(date(int(expiry_year), int(expiry_month), 1), DELIVERY_TYPE_FROM_CODE[code])

    @classmethod
    def from_id(cls, product_id: str) -> Product:
        code, rest = product_id.split("-", 1)
        t = DELIVERY_TYPE_FROM_CODE[code]
        if t == "M":
            y, m = rest.split("-")
            return cls(date(int(y), int(m), 1), "M")
        if t == "Q":
            y, q = rest.split("-Q")
            return cls(date(int(y), 3 * (int(q) - 1) + 1, 1), "Q")
        return cls(date(int(rest), 1, 1), "Y")


# --- trading calendar ---------------------------------------------------------------------

def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return date(year, month, day)


@cache
def holidays(year: int) -> frozenset[date]:
    """Approximate EEX/ECC derivatives holidays (assumption D-005): New Year, Good Friday,
    Easter Monday, 1 May, 24-26 December. 31 December is treated as a business day, which is
    consistent with the quarter/year expiry dates observed in the SPAN file."""
    e = _easter(year)
    return frozenset({date(year, 1, 1), e - timedelta(days=2), e + timedelta(days=1),
                      date(year, 5, 1), date(year, 12, 24), date(year, 12, 25),
                      date(year, 12, 26)})


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def business_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_business_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def add_business_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    remaining = abs(n)
    while remaining:
        d += timedelta(days=step)
        if is_business_day(d):
            remaining -= 1
    return d


def last_trading_day(p: Product) -> date:
    """Expiry rule used when no listing data is available (calendar-based tenor mapping).

    Months trade until the end of delivery (financially settled against the spot index), but the
    tenors used here only ever reference months *before* delivery. Quarters and years expire
    three business days before delivery start (matches all 16 DEBQ/DEBY expiries checked against
    the 2026-10-16 SPAN file, see tests and DECISIONS D-006).
    """
    if p.delivery_type == "M":
        return p.delivery_end
    return add_business_days(p.delivery_start, -3)
