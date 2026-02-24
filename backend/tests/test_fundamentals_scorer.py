"""Unit tests for the fundamentals scorer."""

import pytest
from backend.models.fundamentals import FundamentalData
from backend.scanner.fundamentals_scorer import FundamentalsScorer

scorer = FundamentalsScorer()


def _make_fund(**kwargs) -> FundamentalData:
    defaults = dict(symbol="TEST")
    defaults.update(kwargs)
    return FundamentalData(**defaults)


def test_score_range():
    """Fundamental score should always be 0-100."""
    fund = _make_fund(
        pe_ratio=20,
        revenue_growth_yoy=0.15,
        debt_to_equity=0.5,
        gross_margin=0.45,
        operating_margin=0.15,
        return_on_equity=0.20,
        free_cash_flow_yield=0.05,
    )
    scored = scorer.score(fund)
    assert 0 <= scored.fundamental_score <= 100


def test_high_quality_company():
    """A company with great metrics should score above 70."""
    fund = _make_fund(
        pe_ratio=18,
        revenue_growth_yoy=0.25,
        debt_to_equity=0.2,
        gross_margin=0.65,
        operating_margin=0.30,
        return_on_equity=0.35,
        free_cash_flow_yield=0.08,
    )
    scored = scorer.score(fund)
    assert scored.fundamental_score > 65, f"Score too low: {scored.fundamental_score}"


def test_poor_quality_company():
    """A company with bad metrics should score below 40."""
    fund = _make_fund(
        pe_ratio=80,
        revenue_growth_yoy=-0.15,
        debt_to_equity=4.0,
        gross_margin=0.05,
        operating_margin=-0.10,
        return_on_equity=-0.20,
        free_cash_flow_yield=-0.05,
    )
    scored = scorer.score(fund)
    assert scored.fundamental_score < 45, f"Score too high: {scored.fundamental_score}"


def test_missing_data_returns_neutral():
    """Missing all data should return score near 50."""
    fund = _make_fund()  # all optional fields are None
    scored = scorer.score(fund)
    assert 30 <= scored.fundamental_score <= 70, f"Score not neutral: {scored.fundamental_score}"
