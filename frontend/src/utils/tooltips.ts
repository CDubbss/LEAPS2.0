export const TOOLTIPS = {
  // Filter panel
  dte:          "Days To Expiration: Calendar days remaining until the options expire.",
  iv_rank:      "IV Rank (0–100): Where current implied volatility sits within the 52-week range. Higher = more expensive options.",
  max_cost_pct: "Max Cost %: Caps the debit paid as a % of spread width. E.g. 25% on a $10 spread = max $2.50 debit.",
  spread_width: "Spread Width: Dollar distance between the long and short strikes. Larger width = higher max profit and max loss.",
  ml_quality:   "ML Quality Score: XGBoost model confidence in spread quality (0–100). Returns a placeholder of 50 until the model is trained on historical outcomes.",
  fundamental:  "Fundamental Score (0–100): Company financial health based on P/E ratio, revenue growth, margins, and debt ratios.",
  sentiment:    "Sentiment Score (0–100): FinBERT NLP analysis of recent news articles. Higher = more positive sentiment.",
  pop_filter:   "Probability of Profit: Estimated likelihood the spread expires in-the-money, computed via Black-Scholes.",

  // Results table column headers
  dte_col:      "Days To Expiration: Calendar days until the options expire.",
  iv_rank_col:  "IV Rank: Implied volatility percentile over the past 52 weeks. Low = cheap options, High = expensive options.",
  pop_col:      "Probability of Profit: Black-Scholes estimate that the spread expires profitable.",
  ml_col:       "ML Quality Score: XGBoost model score (0–100). Higher = better expected trade quality.",
  risk_col:     "Composite Risk Score (0–100): Weighted blend of IV Rank, bid-ask quality, fundamentals, sentiment, and liquidity.",

  // SpreadDetailCard — greeks & metrics
  delta:        "Delta (Δ): How much the option price moves per $1 move in the stock. Calls: 0 to 1. Puts: −1 to 0.",
  gamma:        "Gamma (Γ): Rate of change of delta per $1 stock move. High gamma means delta shifts rapidly near expiry.",
  theta:        "Theta (Θ): Daily time decay in dollars. Negative = option loses value each day that passes.",
  vega:         "Vega (ν): P&L change per 1% move in implied volatility. Higher vega = more sensitive to IV changes.",
  rho:          "Rho (ρ): P&L change per 1% change in risk-free interest rates. Typically a small factor for short-dated options.",
  iv_pct:       "Implied Volatility: The market's expectation of future price movement embedded in the option price.",
  bid_ask_q:    "Bid-Ask Quality: How tight the bid-ask spread is (0–100%). 100% = perfectly tight. Low values indicate wide spreads and difficult fills.",
  breakeven:    "Breakeven: The stock price at expiration where the spread neither profits nor loses money.",

  // RiskBreakdownCard
  composite:    "Composite Risk Score: Weighted blend — IV Rank 25%, Bid-Ask 20%, Fundamentals 25%, Sentiment 15%, Liquidity 15%.",
  iv_risk:      "IV Rank Component: Lower IV rank scores better for debit spreads — cheaper options to enter.",
  ba_risk:      "Bid-Ask Component: Tighter bid-ask spreads mean less slippage when entering or exiting the position.",
  fund_risk:    "Fundamental Component: Company financial health. Strong fundamentals reduce risk of adverse stock moves.",
  sent_risk:    "Sentiment Component: Negative recent news can trigger sharp moves against the position.",
  liq_risk:     "Liquidity Component: Based on open interest and volume. Higher liquidity = easier fills and tighter markets.",
} as const;
