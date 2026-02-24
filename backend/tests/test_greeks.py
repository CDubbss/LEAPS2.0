"""Unit tests for the Black-Scholes greeks calculator."""

import math
import pytest
from backend.scanner.greeks_calculator import compute_greeks, compute_probability_of_profit


def test_call_delta_atm():
    """ATM call delta should be approximately 0.5."""
    greeks = compute_greeks(S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type="call")
    assert 0.45 < greeks["delta"] < 0.65, f"ATM call delta out of range: {greeks['delta']}"


def test_put_delta_atm():
    """ATM put delta should be approximately -0.5."""
    greeks = compute_greeks(S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type="put")
    assert -0.65 < greeks["delta"] < -0.35, f"ATM put delta out of range: {greeks['delta']}"


def test_deep_itm_call_delta():
    """Deep ITM call delta should be close to 1.0."""
    greeks = compute_greeks(S=150, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
    assert greeks["delta"] > 0.85, f"Deep ITM call delta too low: {greeks['delta']}"


def test_gamma_positive():
    """Gamma should always be positive for both calls and puts."""
    for option_type in ["call", "put"]:
        greeks = compute_greeks(S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type=option_type)
        assert greeks["gamma"] > 0, f"Gamma negative for {option_type}"


def test_theta_negative_long():
    """Theta should be negative for long options (time decay)."""
    for option_type in ["call", "put"]:
        greeks = compute_greeks(S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type=option_type)
        assert greeks["theta"] < 0, f"Theta positive for long {option_type}"


def test_vega_positive():
    """Vega should be positive for long options."""
    for option_type in ["call", "put"]:
        greeks = compute_greeks(S=100, K=100, T=0.25, r=0.05, sigma=0.20, option_type=option_type)
        assert greeks["vega"] > 0


def test_zero_time_returns_zeros():
    """Zero or negative T should return all zeros to avoid division errors."""
    greeks = compute_greeks(S=100, K=100, T=0, r=0.05, sigma=0.20, option_type="call")
    assert all(v == 0.0 for v in greeks.values())


def test_pop_range():
    """PoP should be between 0 and 1."""
    pop = compute_probability_of_profit(breakeven=105, spot=100, iv=0.25, dte=30)
    assert 0 < pop < 1


def test_pop_otm_spread():
    """Breakeven above spot → PoP < 0.5 for a bull spread."""
    pop = compute_probability_of_profit(breakeven=110, spot=100, iv=0.20, dte=30)
    assert pop < 0.5
