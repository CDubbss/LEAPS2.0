"""
NYSE trading-calendar tests.

These guard a rule that silently cost 26% of the training corpus: yfinance
answers when the market is shut, serving the prior session's chain, so a scan
on a non-trading day logs real quotes under the wrong date (HANDOFF §4.8).

The federal-vs-NYSE divergences are the cases most likely to regress if anyone
swaps this for USFederalHolidayCalendar, so they are asserted explicitly.
"""

from datetime import date

from backend.data.market_calendar import (
    is_market_holiday,
    is_market_open,
    market_closed_reason,
)


# --- Full-day NYSE closures -------------------------------------------------

def test_good_friday_is_closed():
    """Not a federal holiday, but the NYSE shuts. USFederalHolidayCalendar misses this."""
    assert not is_market_open(date(2026, 4, 3))
    assert market_closed_reason(date(2026, 4, 3)) == "holiday"


def test_fixed_and_floating_holidays_closed():
    for d in (
        date(2026, 1, 1),    # New Year's Day
        date(2026, 1, 19),   # MLK Day
        date(2026, 2, 16),   # Presidents Day
        date(2026, 5, 25),   # Memorial Day
        date(2026, 6, 19),   # Juneteenth
        date(2026, 9, 7),    # Labor Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    ):
        assert not is_market_open(d), d


def test_saturday_holiday_observed_on_friday():
    """July 4 2026 is a Saturday, so the NYSE closes Friday July 3."""
    assert date(2026, 7, 4).weekday() == 5
    assert is_market_holiday(date(2026, 7, 3))
    assert not is_market_open(date(2026, 7, 3))


# --- Days the NYSE trades but the federal government does not ---------------

def test_columbus_and_veterans_day_are_trading_days():
    """Federal holidays, but the NYSE is open — must NOT be flagged closed."""
    for d in (date(2026, 10, 12), date(2026, 11, 11)):
        assert is_market_open(d), d
        assert market_closed_reason(d) is None


def test_half_session_counts_as_open():
    """Day after Thanksgiving closes early but trades — quotes are live."""
    assert is_market_open(date(2026, 11, 27))


# --- Weekends ---------------------------------------------------------------

def test_weekend_closed_with_weekend_reason():
    assert market_closed_reason(date(2026, 8, 8)) == "weekend"   # Saturday
    assert market_closed_reason(date(2026, 8, 9)) == "weekend"   # Sunday
    assert not is_market_open(date(2026, 8, 8))


def test_weekend_reason_takes_precedence_over_holiday():
    """A holiday landing on a weekend reports 'weekend' — both mean closed."""
    assert market_closed_reason(date(2026, 7, 4)) == "weekend"


def test_ordinary_weekday_is_open():
    d = date(2026, 8, 11)
    assert is_market_open(d)
    assert market_closed_reason(d) is None


def test_holiday_check_ignores_weekends():
    """is_market_holiday answers only about holidays; weekends are separate."""
    assert not is_market_holiday(date(2026, 8, 8))


def test_calendar_spans_years():
    """Rules must expand correctly outside the year the data happens to cover."""
    assert not is_market_open(date(2027, 1, 1))
    assert not is_market_open(date(2025, 12, 25))
