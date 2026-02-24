"""
Constructs SpreadCandidate objects from filtered option legs.
Implements: Bull Call Spread, Bear Put Spread, LEAPS (single-leg).
"""

import logging
from datetime import date

from backend.models.options import OptionQuote, SpreadCandidate, SpreadType
from backend.scanner.greeks_calculator import compute_probability_of_profit

logger = logging.getLogger(__name__)

# Max OTM % for the long leg of a spread (don't go too far out of the money)
MAX_OTM_PCT = 0.20

# Typical standard spread widths to consider (points)
# We'll derive natural widths from available strikes rather than hardcoding
MAX_SPREAD_WIDTH_STRIKES = 5  # max N strikes apart for spreads


class SpreadConstructor:
    """
    Builds all valid spread combinations from filtered legs.
    Returns a flat list of SpreadCandidate objects.
    """

    def build_all_spreads(
        self,
        calls: list[OptionQuote],
        puts: list[OptionQuote],
        strategies: list[SpreadType],
        spot_price: float,
    ) -> list[SpreadCandidate]:
        spreads = []
        for strategy in strategies:
            if strategy == SpreadType.BULL_CALL:
                spreads.extend(self._build_bull_call_spreads(calls, spot_price))
            elif strategy == SpreadType.LEAPS_SPREAD_CALL:
                spreads.extend(
                    self._build_bull_call_spreads(calls, spot_price, SpreadType.LEAPS_SPREAD_CALL)
                )
            elif strategy == SpreadType.BEAR_PUT:
                spreads.extend(self._build_bear_put_spreads(puts, spot_price))
            elif strategy == SpreadType.LEAP_CALL:
                spreads.extend(self._build_leaps(calls, spot_price, SpreadType.LEAP_CALL))
            elif strategy == SpreadType.LEAP_PUT:
                spreads.extend(self._build_leaps(puts, spot_price, SpreadType.LEAP_PUT))
        return spreads

    def _build_bull_call_spreads(
        self,
        calls: list[OptionQuote],
        spot: float,
        spread_type: SpreadType = SpreadType.BULL_CALL,
    ) -> list[SpreadCandidate]:
        """
        Bull Call Spread: long lower-strike call + short higher-strike call.
        - Net debit = long_ask - short_bid
        - Max profit = spread_width - net_debit
        - Max loss = net_debit
        - Breakeven = long_strike + net_debit
        """
        spreads = []
        # Group by expiration
        by_expiry = self._group_by_expiry(calls)

        for expiry, legs in by_expiry.items():
            sorted_legs = sorted(legs, key=lambda x: x.strike)
            dte = (expiry - date.today()).days

            for i, long_leg in enumerate(sorted_legs):
                # Long leg should be at or below the money (not too far OTM)
                if long_leg.strike > spot * (1 + MAX_OTM_PCT):
                    break

                # Short leg: must be higher strike, same expiry, within N strikes
                for short_leg in sorted_legs[i + 1: i + 1 + MAX_SPREAD_WIDTH_STRIKES]:
                    if short_leg.bid <= 0:
                        continue

                    net_debit = round(long_leg.ask - short_leg.bid, 4)
                    if net_debit <= 0:
                        continue  # would be a credit — not a debit spread

                    spread_width = round(short_leg.strike - long_leg.strike, 2)
                    max_profit = round(spread_width - net_debit, 4)
                    if max_profit <= 0:
                        continue  # unfavorable: cost >= width

                    breakeven = round(long_leg.strike + net_debit, 4)

                    # Use long leg IV for PoP (conservative)
                    pop = compute_probability_of_profit(
                        breakeven=breakeven,
                        spot=spot,
                        iv=long_leg.implied_volatility,
                        dte=dte,
                    )

                    # Bid-ask quality: average of both legs (0=poor, 1=tight)
                    ba_quality = self._bid_ask_quality(long_leg, short_leg)

                    spreads.append(
                        SpreadCandidate(
                            underlying=long_leg.underlying,
                            spread_type=spread_type,
                            expiration=expiry,
                            dte=dte,
                            long_leg=long_leg,
                            short_leg=short_leg,
                            net_debit=net_debit,
                            max_profit=max_profit,
                            max_loss=net_debit,
                            breakeven=breakeven,
                            probability_of_profit=pop,
                            bid_ask_quality_score=ba_quality,
                            iv_rank=0.0,  # filled by scanner after IV rank lookup
                            spread_width=spread_width,
                        )
                    )
        return spreads

    def _build_bear_put_spreads(
        self, puts: list[OptionQuote], spot: float
    ) -> list[SpreadCandidate]:
        """
        Bear Put Spread: long higher-strike put + short lower-strike put.
        - Net debit = long_ask - short_bid
        - Max profit = spread_width - net_debit
        - Max loss = net_debit
        - Breakeven = long_strike - net_debit
        """
        spreads = []
        by_expiry = self._group_by_expiry(puts)

        for expiry, legs in by_expiry.items():
            sorted_legs = sorted(legs, key=lambda x: x.strike, reverse=True)
            dte = (expiry - date.today()).days

            for i, long_leg in enumerate(sorted_legs):
                # Long leg: at or slightly above the money
                if long_leg.strike < spot * (1 - MAX_OTM_PCT):
                    break

                for short_leg in sorted_legs[i + 1: i + 1 + MAX_SPREAD_WIDTH_STRIKES]:
                    if short_leg.bid <= 0:
                        continue

                    net_debit = round(long_leg.ask - short_leg.bid, 4)
                    if net_debit <= 0:
                        continue

                    spread_width = round(long_leg.strike - short_leg.strike, 2)
                    max_profit = round(spread_width - net_debit, 4)
                    if max_profit <= 0:
                        continue

                    breakeven = round(long_leg.strike - net_debit, 4)

                    # PoP: prob that stock falls below breakeven
                    pop = compute_probability_of_profit(
                        breakeven=breakeven,
                        spot=spot,
                        iv=long_leg.implied_volatility,
                        dte=dte,
                    )
                    pop = 1.0 - pop  # bear spread profits on downside

                    ba_quality = self._bid_ask_quality(long_leg, short_leg)

                    spreads.append(
                        SpreadCandidate(
                            underlying=long_leg.underlying,
                            spread_type=SpreadType.BEAR_PUT,
                            expiration=expiry,
                            dte=dte,
                            long_leg=long_leg,
                            short_leg=short_leg,
                            net_debit=net_debit,
                            max_profit=max_profit,
                            max_loss=net_debit,
                            breakeven=breakeven,
                            probability_of_profit=round(max(0.01, min(0.99, pop)), 4),
                            bid_ask_quality_score=ba_quality,
                            iv_rank=0.0,
                            spread_width=spread_width,
                        )
                    )
        return spreads

    def _build_leaps(
        self,
        options: list[OptionQuote],
        spot: float,
        spread_type: SpreadType,
    ) -> list[SpreadCandidate]:
        """
        LEAPS single-leg: long deep ITM call or put with DTE >= 365.
        Selection criteria: delta >= 0.70 (deep ITM, stock replacement).
        """
        spreads = []
        is_call = spread_type == SpreadType.LEAP_CALL

        for opt in options:
            dte = (opt.expiration - date.today()).days
            if dte < 365:
                continue

            # For calls: want high delta (deep ITM); for puts: want low delta (deep ITM put)
            delta_threshold = 0.65
            abs_delta = abs(opt.delta)
            if abs_delta < delta_threshold:
                continue

            premium = opt.ask
            if premium <= 0:
                continue

            # LEAPS: no short leg, max loss = premium paid
            pop = 0.5  # rough placeholder for single-leg (hard to define simply)

            spreads.append(
                SpreadCandidate(
                    underlying=opt.underlying,
                    spread_type=spread_type,
                    expiration=opt.expiration,
                    dte=dte,
                    long_leg=opt,
                    short_leg=None,
                    net_debit=premium,
                    max_profit=9999.0,  # unlimited for long call; practical max for put
                    max_loss=premium,
                    breakeven=opt.strike + premium if is_call else opt.strike - premium,
                    probability_of_profit=pop,
                    bid_ask_quality_score=self._bid_ask_quality_single(opt),
                    iv_rank=0.0,
                    spread_width=0.0,
                )
            )
        return spreads

    @staticmethod
    def _group_by_expiry(
        options: list[OptionQuote],
    ) -> dict[date, list[OptionQuote]]:
        groups: dict[date, list[OptionQuote]] = {}
        for opt in options:
            groups.setdefault(opt.expiration, []).append(opt)
        return groups

    @staticmethod
    def _bid_ask_quality(long_leg: OptionQuote, short_leg: OptionQuote) -> float:
        """
        Score 0-1: how tight are the bid-ask spreads?
        1.0 = perfectly tight, 0.0 = worst acceptable.
        """
        def leg_quality(opt: OptionQuote) -> float:
            mid = (opt.bid + opt.ask) / 2
            if mid <= 0:
                return 0.0
            spread_pct = (opt.ask - opt.bid) / mid
            return max(0.0, 1.0 - spread_pct / 0.15)

        return round((leg_quality(long_leg) + leg_quality(short_leg)) / 2, 4)

    @staticmethod
    def _bid_ask_quality_single(opt: OptionQuote) -> float:
        mid = (opt.bid + opt.ask) / 2
        if mid <= 0:
            return 0.0
        spread_pct = (opt.ask - opt.bid) / mid
        return round(max(0.0, 1.0 - spread_pct / 0.15), 4)
