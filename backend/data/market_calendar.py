"""
NYSE trading calendar — is the options market open on a given date?

Why this exists
---------------
Scans run from a scheduler. When the market is closed, yfinance still answers:
it serves the *previous session's closing chain*. Those quotes are real, but
they get logged under the wrong entry_date and are usually near-duplicates of
the previous trading day's rows. That silently contaminated 23% of the training
corpus before it was caught (HANDOFF §4.8).

Why not USFederalHolidayCalendar
--------------------------------
The NYSE calendar is NOT the federal calendar:
  - NYSE closes on Good Friday, which is not a federal holiday.
  - NYSE trades on Columbus Day and Veterans Day, which are federal holidays.
Using the federal list would both miss a real closure and skip two real
trading days.

Scope: full-day closures only. Half sessions (the day after Thanksgiving,
Christmas Eve) trade normally until early close, so their quotes are live and
those days are treated as open. Ad-hoc closures (national days of mourning,
weather) are not modelled — they are rare and unpredictable; the
`market_closed` flag on logged rows is the backstop for those.
"""

from datetime import date
from functools import lru_cache

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)


class NYSEHolidayCalendar(AbstractHolidayCalendar):
    """Full-day NYSE closures. `nearest_workday` implements the NYSE
    observance rule: a Saturday holiday shifts to Friday, Sunday to Monday."""

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2021-06-18",
                observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


@lru_cache(maxsize=8)
def _holidays(year_start: int, year_end: int) -> frozenset[date]:
    """Holiday dates for a year span. Cached — the rule expansion is not free."""
    idx = NYSEHolidayCalendar().holidays(
        start=f"{year_start}-01-01", end=f"{year_end}-12-31"
    )
    return frozenset(d.date() for d in pd.DatetimeIndex(idx))


def is_market_holiday(d: date) -> bool:
    """True if d is a full-day NYSE closure (weekends excluded — see is_market_open)."""
    return d in _holidays(d.year, d.year)


def is_market_open(d: date) -> bool:
    """True if the NYSE trades a full or half session on d."""
    return d.weekday() < 5 and not is_market_holiday(d)


def market_closed_reason(d: date) -> str | None:
    """'weekend' | 'holiday' | None — why the market is shut, for logging."""
    if d.weekday() >= 5:
        return "weekend"
    if is_market_holiday(d):
        return "holiday"
    return None
