from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class OptionType(str, Enum):
    CALL = "call"
    PUT = "put"


class SpreadType(str, Enum):
    BULL_CALL = "bull_call"
    BEAR_PUT = "bear_put"
    LEAP_CALL = "leap_call"
    LEAP_PUT = "leap_put"
    LEAPS_SPREAD_CALL = "leaps_spread_call"
    EARNINGS_CALL = "earnings_call"
    EARNINGS_PUT = "earnings_put"


class OptionQuote(BaseModel):
    symbol: str
    underlying: str
    expiration: date
    strike: float
    option_type: OptionType
    bid: float
    ask: float
    mid: float
    last: float
    volume: int
    open_interest: int
    implied_volatility: float  # decimal, e.g. 0.35 = 35%
    delta: float
    gamma: float
    theta: float  # per day
    vega: float   # per 1% IV change
    rho: float


class OptionsChain(BaseModel):
    underlying: str
    spot_price: float
    quote_time: str
    expirations: list[date]
    calls: list[OptionQuote]
    puts: list[OptionQuote]


class SpreadCandidate(BaseModel):
    underlying: str
    spread_type: SpreadType
    expiration: date
    dte: int
    long_leg: OptionQuote
    short_leg: Optional[OptionQuote] = None  # None for single-leg LEAPS
    net_debit: float        # cost to enter (positive = debit)
    max_profit: float
    max_loss: float
    breakeven: float
    probability_of_profit: float  # Black-Scholes estimated
    bid_ask_quality_score: float  # 0-1, higher = tighter spread
    iv_rank: float                # 0-100
    spread_width: float = Field(default=0.0)    # short_strike - long_strike (0 for LEAPS)
    spot_price: float = Field(default=0.0)     # underlying price at scan time
    iv_skew: float = Field(default=0.0)        # 25-delta put IV minus 25-delta call IV
    price_52w_high: float = Field(default=0.0) # from yfinance fast_info
    price_52w_low: float = Field(default=0.0)  # from yfinance fast_info
    hv_30d: Optional[float] = None             # 30-day realized volatility (annualized)
    iv_52w_high: Optional[float] = None        # 52-week IV high (HV proxy)
    iv_52w_low: Optional[float] = None         # 52-week IV low (HV proxy)
    days_to_earnings: Optional[int] = None     # calendar days until next earnings
    next_earnings_date: Optional[date] = None  # absolute date of next earnings event
