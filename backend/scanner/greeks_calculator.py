"""
Black-Scholes option greeks calculator.
Used to compute delta, gamma, theta, vega, rho from yfinance chain data
since yfinance does not provide greeks natively.
"""

import math

from scipy.stats import norm


def compute_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str,
) -> dict[str, float]:
    """
    Compute Black-Scholes greeks.

    Args:
        S: Current stock price
        K: Strike price
        T: Time to expiration in years (e.g. 30/365 for 30 DTE)
        r: Risk-free interest rate (decimal, e.g. 0.05 for 5%)
        sigma: Implied volatility (decimal, e.g. 0.30 for 30%)
        option_type: "call" or "put"

    Returns:
        dict with keys: delta, gamma, theta, vega, rho
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    is_call = option_type.lower() == "call"
    sign = 1 if is_call else -1

    # Delta
    delta = float(norm.cdf(sign * d1)) * sign
    # For puts: delta = N(d1) - 1, which equals -N(-d1)
    if not is_call:
        delta = float(norm.cdf(d1)) - 1.0

    # Gamma (same for calls and puts)
    gamma = float(norm.pdf(d1)) / (S * sigma * math.sqrt(T))

    # Theta (per calendar day, not annualized)
    theta_call = (
        -(S * float(norm.pdf(d1)) * sigma) / (2 * math.sqrt(T))
        - r * K * math.exp(-r * T) * float(norm.cdf(d2))
    ) / 365
    if is_call:
        theta = theta_call
    else:
        theta = (
            -(S * float(norm.pdf(d1)) * sigma) / (2 * math.sqrt(T))
            + r * K * math.exp(-r * T) * float(norm.cdf(-d2))
        ) / 365

    # Vega (per 1% change in IV)
    vega = S * float(norm.pdf(d1)) * math.sqrt(T) / 100

    # Rho (per 1% change in interest rate)
    if is_call:
        rho = K * T * math.exp(-r * T) * float(norm.cdf(d2)) / 100
    else:
        rho = -K * T * math.exp(-r * T) * float(norm.cdf(-d2)) / 100

    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 6),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
        "rho": round(rho, 6),
    }


def compute_probability_of_profit(
    breakeven: float, spot: float, iv: float, dte: int
) -> float:
    """
    Approximate probability of profit using Black-Scholes lognormal distribution.
    For a long spread: PoP ≈ probability that stock price > breakeven at expiry.
    """
    T = max(dte / 365.0, 1 / 365.0)
    if iv <= 0 or T <= 0 or spot <= 0 or breakeven <= 0:
        return 0.5

    d2 = (math.log(spot / breakeven) - 0.5 * iv**2 * T) / (iv * math.sqrt(T))
    pop = float(norm.cdf(d2))
    return round(max(0.01, min(0.99, pop)), 4)
