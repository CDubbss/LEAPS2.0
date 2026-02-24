import React from "react";
import type { RankedSpread } from "@/types";
import {
  formatCurrency,
  formatDate,
  formatDTE,
  formatIV,
  formatGreek,
  formatPct,
  spreadTypeLabel,
  spreadTypeBadgeColor,
} from "@/utils/formatting";
import { TrendingUp, TrendingDown, Target } from "lucide-react";
import { InfoTooltip } from "@/components/ui/Tooltip";
import { TOOLTIPS } from "@/utils/tooltips";

interface Props {
  item: RankedSpread;
}

export const SpreadDetailCard: React.FC<Props> = ({ item }) => {
  const { spread } = item;
  const long = spread.long_leg;
  const short = spread.short_leg;

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-2xl font-bold text-white">
              {spread.underlying}
            </span>
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium ${spreadTypeBadgeColor(
                spread.spread_type
              )}`}
            >
              {spreadTypeLabel(spread.spread_type)}
            </span>
          </div>
          <p className="text-sm text-gray-400 mt-1">
            Exp: {formatDate(spread.expiration)} · {formatDTE(spread.dte)}
          </p>
        </div>
        <div className="text-right">
          <div className="text-xl font-bold text-white">
            {formatCurrency(spread.net_debit)}
          </div>
          <div className="text-xs text-gray-400">Net Debit</div>
        </div>
      </div>

      {/* P/L Summary */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-gray-700/50 rounded p-3 text-center">
          <div className="flex items-center justify-center gap-1 text-green-400 mb-1">
            <TrendingUp size={14} />
            <span className="text-xs">Max Profit</span>
          </div>
          <div className="text-lg font-bold text-green-400">
            {spread.max_profit >= 9999
              ? "Unlimited"
              : formatCurrency(spread.max_profit)}
          </div>
        </div>
        <div className="bg-gray-700/50 rounded p-3 text-center">
          <div className="flex items-center justify-center gap-1 text-red-400 mb-1">
            <TrendingDown size={14} />
            <span className="text-xs">Max Loss</span>
          </div>
          <div className="text-lg font-bold text-red-400">
            {formatCurrency(spread.max_loss)}
          </div>
        </div>
        <div className="bg-gray-700/50 rounded p-3 text-center">
          <div className="flex items-center justify-center gap-1 text-gray-400 mb-1">
            <Target size={14} />
            <span className="text-xs">
              Breakeven <InfoTooltip content={TOOLTIPS.breakeven} />
            </span>
          </div>
          <div className="text-lg font-bold text-gray-200">
            {formatCurrency(spread.breakeven)}
          </div>
        </div>
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 gap-2 text-sm">
        <MetricRow
          label="Probability of Profit"
          value={formatPct(spread.probability_of_profit)}
          tooltip={TOOLTIPS.pop_filter}
        />
        <MetricRow
          label="IV Rank"
          value={`${spread.iv_rank.toFixed(1)}`}
          tooltip={TOOLTIPS.iv_rank_col}
        />
        <MetricRow
          label="Bid-Ask Quality"
          value={`${(spread.bid_ask_quality_score * 100).toFixed(0)}%`}
          tooltip={TOOLTIPS.bid_ask_q}
        />
        {spread.spread_width > 0 && (
          <MetricRow
            label="Spread Width"
            value={formatCurrency(spread.spread_width)}
            tooltip={TOOLTIPS.spread_width}
          />
        )}
      </div>

      {/* Long Leg */}
      <div>
        <div className="text-xs font-medium text-gray-400 uppercase mb-2">
          Long Leg
        </div>
        <LegRow option={long} label="Buy" />
      </div>

      {/* Short Leg */}
      {short && (
        <div>
          <div className="text-xs font-medium text-gray-400 uppercase mb-2">
            Short Leg
          </div>
          <LegRow option={short} label="Sell" />
        </div>
      )}
    </div>
  );
};

const MetricRow: React.FC<{ label: string; value: string; tooltip?: string }> = ({
  label,
  value,
  tooltip,
}) => (
  <div className="flex justify-between items-center py-1 border-b border-gray-700/50">
    <span className="text-gray-400 text-xs">
      {label}
      {tooltip && <InfoTooltip content={tooltip} />}
    </span>
    <span className="text-gray-200 text-xs font-medium">{value}</span>
  </div>
);

const LegRow: React.FC<{ option: import("@/types").OptionQuote; label: string }> = ({
  option,
  label,
}) => (
  <div className="bg-gray-700/30 rounded p-3 text-xs">
    <div className="flex justify-between mb-2 min-w-0 gap-2">
      <span className="font-medium text-white min-w-0 truncate">
        {label} {option.strike} {option.option_type.toUpperCase()}
      </span>
      <span className="text-gray-300 whitespace-nowrap flex-shrink-0">
        Bid {formatCurrency(option.bid)} / Ask {formatCurrency(option.ask)}
      </span>
    </div>
    <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-gray-400 lg:grid-cols-4">
      <span className="overflow-hidden truncate">IV <InfoTooltip content={TOOLTIPS.iv_pct} />: {formatIV(option.implied_volatility)}</span>
      <span className="overflow-hidden truncate">Δ <InfoTooltip content={TOOLTIPS.delta} />: {formatGreek(option.delta)}</span>
      <span className="overflow-hidden truncate">Γ <InfoTooltip content={TOOLTIPS.gamma} />: {formatGreek(option.gamma, 5)}</span>
      <span className="overflow-hidden truncate">Θ <InfoTooltip content={TOOLTIPS.theta} />: {formatGreek(option.theta)}</span>
      <span className="overflow-hidden truncate">Vol: {option.volume.toLocaleString()}</span>
      <span className="overflow-hidden truncate">OI: {option.open_interest.toLocaleString()}</span>
      <span className="overflow-hidden truncate">ν <InfoTooltip content={TOOLTIPS.vega} />: {formatGreek(option.vega)}</span>
    </div>
  </div>
);
