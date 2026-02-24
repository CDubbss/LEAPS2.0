from pydantic import BaseModel


class FeatureVector(BaseModel):
    # --- Options mechanics ---
    iv_rank: float                  # 0-100
    iv_percentile: float            # 0-100
    bid_ask_spread_pct: float       # decimal, e.g. 0.05 = 5%
    delta: float                    # absolute value, 0-1
    gamma: float
    theta_per_day: float            # negative for long options
    dte: float                      # days to expiration
    moneyness: float                # (strike - spot) / spot

    # --- Spread structure ---
    spread_width_pct: float         # spread_width / spot_price (0 for LEAPS)
    max_risk_reward_ratio: float    # max_profit / max_loss
    net_debit_pct_of_spread: float  # net_debit / spread_width (0-1 for spreads)

    # --- Volatility regime ---
    iv_vs_hv_ratio: float           # current IV / 30-day HV
    iv_skew: float                  # placeholder, 0 if unavailable

    # --- Fundamental quality ---
    pe_ratio: float                 # 0 if N/A
    revenue_growth: float           # decimal
    debt_to_equity: float           # 0 if N/A
    gross_margin: float             # decimal
    fundamental_score: float        # 0-100

    # --- Sentiment ---
    sentiment_score: float          # 0-100
    sentiment_compound: float       # -1 to 1

    # --- Technical / price context ---
    price_vs_52w_high_pct: float    # (price - 52wh) / 52wh, negative = below high
    price_vs_52w_low_pct: float     # (price - 52wl) / 52wl, positive = above low
    sector_relative_strength: float  # placeholder, 0.5 if unavailable


class MLPrediction(BaseModel):
    spread_quality_score: float         # 0-100, primary ranking signal
    expected_return_pct: float          # estimated annualized return %
    probability_of_profit: float        # ML-estimated PoP (0-1)
    confidence: float                   # model confidence 0-1
    feature_importances: dict[str, float]  # top contributing features
    is_placeholder: bool = False        # True when model not yet trained
