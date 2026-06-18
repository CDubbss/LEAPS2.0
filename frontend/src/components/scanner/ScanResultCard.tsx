/**
 * ScanResultCard — mobile card view for a single RankedSpread row.
 *
 * Shown on screens < lg instead of the table row.
 * Tapping the card selects it (opens detail sheet).
 * Tapping the ticker symbol opens the TickerModal.
 *
 * Layout (TOS-style dense card):
 *   ┌──────────────────────────────────────┐
 *   │ #1  AAPL  [LEAPS Call]        ML 82 │
 *   │ Debit $3.20 · MaxProfit $680 · PoP 64%│
 *   │ Exp Jan 16 '26 · 410d · IVR 34       │
 *   └──────────────────────────────────────┘
 *
 * To restyle cards globally: edit the className strings in this file.
 */
import React from "react";
import type { RankedSpread } from "@/types";
import {
  formatCurrency,
  formatDate,
  formatDTE,
  formatPct,
  scoreColor,
  spreadTypeLabel,
  spreadTypeBadgeColor,
} from "@/utils/formatting";
import { cn } from "@/utils/cn";

interface ScanResultCardProps {
  item: RankedSpread;
  isSelected: boolean;
  onSelect: () => void;
  onTickerClick: (e: React.MouseEvent) => void;
}

export const ScanResultCard: React.FC<ScanResultCardProps> = ({
  item,
  isSelected,
  onSelect,
  onTickerClick,
}) => {
  const { spread, ml_prediction, risk_score } = item;
  const score = ml_prediction.spread_quality_score;

  return (
    <div
      onClick={onSelect}
      className={cn(
        "px-3 py-2.5 border-b border-gray-800 cursor-pointer transition-colors",
        isSelected
          ? "bg-sky-900/30 border-b-sky-700/50"
          : "hover:bg-gray-800/50 active:bg-gray-800"
      )}
    >
      {/* Row 1: rank · ticker · strategy badge · ML score */}
      <div className="flex items-center gap-2 mb-1">
        <span className="text-gray-500 text-xs font-mono w-5 shrink-0">
          #{item.rank}
        </span>

        <button
          className="font-bold text-sky-400 text-sm leading-none hover:underline"
          onClick={onTickerClick}
        >
          {spread.underlying}
        </button>

        <span
          className={cn(
            "px-1.5 py-0.5 rounded text-[10px] font-medium leading-none",
            spreadTypeBadgeColor(spread.spread_type)
          )}
        >
          {spreadTypeLabel(spread.spread_type)}
        </span>

        <div className="ml-auto flex items-center gap-1.5 shrink-0">
          {/* Mini score bar */}
          <div className="w-12 bg-gray-700 rounded-full h-1">
            <div
              className={cn("h-1 rounded-full", scoreBarColor(score))}
              style={{ width: `${score}%` }}
            />
          </div>
          <span className={cn("text-xs font-bold tabular-nums", scoreColor(score))}>
            {score.toFixed(0)}
          </span>
        </div>
      </div>

      {/* Row 2: key metrics */}
      <div className="flex items-center gap-3 text-[11px] text-gray-400 font-mono pl-7">
        <span>
          <span className="text-gray-300">{formatCurrency(spread.net_debit)}</span>
          <span className="text-gray-600 ml-0.5">debit</span>
        </span>
        <span className="text-gray-700">·</span>
        <span>
          <span className="text-green-400">
            {spread.max_profit >= 9999
              ? "∞"
              : formatCurrency(spread.max_profit * 100)}
          </span>
          <span className="text-gray-600 ml-0.5">max</span>
        </span>
        <span className="text-gray-700">·</span>
        <span>
          <span className="text-gray-300">
            {formatPct(spread.probability_of_profit, 0)}
          </span>
          <span className="text-gray-600 ml-0.5">PoP</span>
        </span>
        {/* Risk score chip */}
        <span className="ml-auto shrink-0">
          <span className={cn("font-medium", scoreColor(risk_score.composite_score))}>
            R{risk_score.composite_score.toFixed(0)}
          </span>
        </span>
      </div>

      {/* Row 3: expiry · DTE · IV rank · earnings */}
      <div className="flex items-center gap-3 text-[11px] text-gray-500 pl-7 mt-0.5">
        <span>{formatDate(spread.expiration)}</span>
        <span className="text-gray-700">·</span>
        <span>{formatDTE(spread.dte)}</span>
        <span className="text-gray-700">·</span>
        <span>IVR {spread.iv_rank?.toFixed(0) ?? "—"}</span>
        {spread.days_to_earnings != null && (
          <>
            <span className="text-gray-700">·</span>
            <span
              className={cn(
                "font-medium",
                spread.days_to_earnings <= 20
                  ? "text-red-400"
                  : spread.days_to_earnings <= 35
                  ? "text-amber-400"
                  : "text-gray-400"
              )}
              title={spread.next_earnings_date ?? undefined}
            >
              ER {spread.days_to_earnings}d
            </span>
          </>
        )}
      </div>
    </div>
  );
};

/** Map score → progress bar color class (separate from text color). */
function scoreBarColor(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 50) return "bg-yellow-500";
  return "bg-red-500";
}
