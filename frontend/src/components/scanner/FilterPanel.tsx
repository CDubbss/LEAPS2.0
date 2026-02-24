import React, { useState } from "react";
import { useScannerStore } from "@/store/scannerStore";
import type { SpreadType } from "@/types";
import { SPREAD_TYPE_LABELS } from "@/types";
import { ScanIcon, RotateCcw, Plus, X } from "lucide-react";
import { InfoTooltip } from "@/components/ui/Tooltip";
import { TOOLTIPS } from "@/utils/tooltips";

const STRATEGY_OPTIONS: SpreadType[] = [
  "leap_call",
  "leap_put",
  "leaps_spread_call",
];

const PRESET_WIDTHS = [5, 10, 15, 20];

export const FilterPanel: React.FC = () => {
  const { filters, setFilters, resetFilters, runScan, isLoading } =
    useScannerStore();
  const [symbolInput, setSymbolInput] = useState("");

  const toggleStrategy = (strategy: SpreadType) => {
    const current = filters.strategies;
    if (current.includes(strategy)) {
      setFilters({ strategies: current.filter((s) => s !== strategy) });
    } else {
      setFilters({ strategies: [...current, strategy] });
    }
  };

  const addSymbol = () => {
    const sym = symbolInput.toUpperCase().trim();
    if (!sym) return;
    const existing = filters.symbols || [];
    if (!existing.includes(sym)) {
      setFilters({ symbols: [...existing, sym] });
    }
    setSymbolInput("");
  };

  const removeSymbol = (sym: string) => {
    const existing = filters.symbols || [];
    const updated = existing.filter((s) => s !== sym);
    setFilters({ symbols: updated.length > 0 ? updated : null });
  };

  return (
    <aside className="w-72 bg-gray-900 border-r border-gray-700 flex flex-col h-full overflow-y-auto">
      <div className="p-4 border-b border-gray-700">
        <h2 className="text-lg font-bold text-white">Scanner Filters</h2>
        <p className="text-xs text-gray-400 mt-1">
          Customize criteria for options scanning
        </p>
      </div>

      <div className="flex-1 p-4 space-y-6">
        {/* Symbol Input */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Symbols{" "}
            <span className="text-gray-500 font-normal">
              (empty = full universe)
            </span>
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={symbolInput}
              onChange={(e) => setSymbolInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addSymbol()}
              placeholder="e.g. AAPL"
              className="flex-1 bg-gray-800 border border-gray-600 text-white text-sm rounded px-3 py-2 focus:outline-none focus:border-brand-500"
            />
            <button
              onClick={addSymbol}
              className="p-2 bg-brand-600 hover:bg-brand-500 text-white rounded"
            >
              <Plus size={16} />
            </button>
          </div>
          {filters.symbols && filters.symbols.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {filters.symbols.map((sym) => (
                <span
                  key={sym}
                  className="inline-flex items-center gap-1 px-2 py-1 bg-gray-700 text-white text-xs rounded"
                >
                  {sym}
                  <button
                    onClick={() => removeSymbol(sym)}
                    className="text-gray-400 hover:text-white"
                  >
                    <X size={10} />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Strategies */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Strategies
          </label>
          <div className="space-y-2">
            {STRATEGY_OPTIONS.map((strategy) => (
              <label
                key={strategy}
                className="flex items-center gap-3 cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={filters.strategies.includes(strategy)}
                  onChange={() => toggleStrategy(strategy)}
                  className="w-4 h-4 accent-sky-500"
                />
                <span className="text-sm text-gray-300">
                  {SPREAD_TYPE_LABELS[strategy]}
                </span>
              </label>
            ))}
          </div>
        </div>

        {/* DTE Range */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            DTE Range (Spreads) <InfoTooltip content={TOOLTIPS.dte} />
          </label>
          <div className="flex gap-2 items-center">
            <input
              type="number"
              value={filters.min_dte}
              onChange={(e) =>
                setFilters({ min_dte: Number(e.target.value) })
              }
              min={0}
              max={365}
              className="w-20 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
            />
            <span className="text-gray-400 text-sm">to</span>
            <input
              type="number"
              value={filters.max_dte}
              onChange={(e) =>
                setFilters({ max_dte: Number(e.target.value) })
              }
              min={0}
              max={365}
              className="w-20 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
            />
            <span className="text-gray-400 text-xs">days</span>
          </div>
        </div>

        {/* Long Leg Delta Range */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            Long Leg Delta <InfoTooltip content={TOOLTIPS.delta_filter} />
          </label>
          <div className="flex gap-2 items-center">
            <input
              type="number"
              value={filters.min_long_delta}
              onChange={(e) =>
                setFilters({ min_long_delta: Number(e.target.value) })
              }
              min={0}
              max={1}
              step={0.01}
              placeholder="Min"
              className="w-20 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
            />
            <span className="text-gray-400 text-sm">to</span>
            <input
              type="number"
              value={filters.max_long_delta}
              onChange={(e) =>
                setFilters({ max_long_delta: Number(e.target.value) })
              }
              min={0}
              max={1}
              step={0.01}
              placeholder="Max"
              className="w-20 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
            />
          </div>
          <p className="text-xs text-gray-500 mt-1">0.00–1.00 · e.g. 0.15–0.35 for OTM</p>
        </div>

        {/* IV Rank Range */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-2">
            IV Rank Range <InfoTooltip content={TOOLTIPS.iv_rank} />
          </label>
          <div className="flex gap-2 items-center">
            <input
              type="number"
              value={filters.min_iv_rank}
              onChange={(e) =>
                setFilters({ min_iv_rank: Number(e.target.value) })
              }
              min={0}
              max={100}
              className="w-20 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
            />
            <span className="text-gray-400 text-sm">to</span>
            <input
              type="number"
              value={filters.max_iv_rank}
              onChange={(e) =>
                setFilters({ max_iv_rank: Number(e.target.value) })
              }
              min={0}
              max={100}
              className="w-20 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
            />
          </div>
        </div>

        {/* Minimum Scores */}
        <div className="space-y-3">
          <label className="block text-sm font-medium text-gray-300">
            Minimum Scores
          </label>
          <SliderRow
            label="Fundamental"
            value={filters.min_fundamental_score}
            onChange={(v) => setFilters({ min_fundamental_score: v })}
            tooltip={TOOLTIPS.fundamental}
          />
          <SliderRow
            label="Sentiment"
            value={filters.min_sentiment_score}
            onChange={(v) => setFilters({ min_sentiment_score: v })}
            tooltip={TOOLTIPS.sentiment}
          />
          <SliderRow
            label="ML Quality"
            value={filters.min_ml_quality_score}
            onChange={(v) => setFilters({ min_ml_quality_score: v })}
            tooltip={TOOLTIPS.ml_quality}
          />
        </div>

        {/* Liquidity */}
        <div className="space-y-3">
          <label className="block text-sm font-medium text-gray-300">
            Liquidity Filters
          </label>
          <div>
            <label className="text-xs text-gray-400">Min Volume</label>
            <input
              type="number"
              value={filters.min_volume}
              onChange={(e) =>
                setFilters({ min_volume: Number(e.target.value) })
              }
              className="w-full mt-1 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
            />
          </div>
          <div>
            <label className="text-xs text-gray-400">Min Open Interest</label>
            <input
              type="number"
              value={filters.min_open_interest}
              onChange={(e) =>
                setFilters({ min_open_interest: Number(e.target.value) })
              }
              className="w-full mt-1 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
            />
          </div>
        </div>

        {/* Spread Controls */}
        <div className="space-y-4">
          <label className="block text-sm font-medium text-gray-300">
            Spread Controls
          </label>

          {/* Target spread widths */}
          <div>
            <label className="text-xs text-gray-400 mb-2 block">
              Spread Width{" "}
              <span className="text-gray-500">(select to pin exact width)</span>
              <InfoTooltip content={TOOLTIPS.spread_width} />
            </label>
            <div className="flex flex-wrap gap-2 mb-2">
              {PRESET_WIDTHS.map((w) => {
                const active = filters.target_spread_widths.includes(w);
                return (
                  <button
                    key={w}
                    onClick={() => {
                      const widths = filters.target_spread_widths;
                      setFilters({
                        target_spread_widths: active
                          ? widths.filter((x) => x !== w)
                          : [...widths, w],
                      });
                    }}
                    className={`px-3 py-1 rounded text-xs font-medium border transition-colors ${
                      active
                        ? "bg-sky-600 border-sky-500 text-white"
                        : "bg-gray-800 border-gray-600 text-gray-300 hover:border-gray-400"
                    }`}
                  >
                    ${w}
                  </button>
                );
              })}
            </div>
            <input
              type="number"
              min={1}
              placeholder="Max width ($)"
              value={filters.max_spread_width ?? ""}
              onChange={(e) =>
                setFilters({
                  max_spread_width: e.target.value
                    ? Number(e.target.value)
                    : null,
                })
              }
              className="w-full bg-gray-800 border border-gray-600 text-white text-sm rounded px-3 py-2 focus:outline-none focus:border-sky-500"
            />
          </div>

          {/* Max cost % of spread */}
          <div>
            <div className="flex justify-between text-xs mb-1">
              <span className="text-gray-400">
                Max Cost % of Spread <InfoTooltip content={TOOLTIPS.max_cost_pct} />
              </span>
              <span className="text-sky-400 font-medium">
                {Math.round(filters.max_debit_pct_of_spread * 100)}%
              </span>
            </div>
            <input
              type="range"
              min={5}
              max={50}
              step={5}
              value={Math.round(filters.max_debit_pct_of_spread * 100)}
              onChange={(e) =>
                setFilters({
                  max_debit_pct_of_spread: Number(e.target.value) / 100,
                })
              }
              className="w-full accent-sky-500"
            />
            <div className="flex justify-between text-xs text-gray-500 mt-1">
              <span>5%</span>
              <span>50%</span>
            </div>
          </div>

          {/* Max net debit */}
          <div>
            <label className="text-xs text-gray-400 mb-1 block">
              Max Net Debit ($)
            </label>
            <input
              type="number"
              min={0}
              step={0.5}
              placeholder="No limit"
              value={filters.max_net_debit ?? ""}
              onChange={(e) =>
                setFilters({
                  max_net_debit: e.target.value ? Number(e.target.value) : null,
                })
              }
              className="w-full bg-gray-800 border border-gray-600 text-white text-sm rounded px-3 py-2 focus:outline-none focus:border-sky-500"
            />
          </div>
        </div>

        {/* Max Results */}
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1">
            Max Results
          </label>
          <input
            type="number"
            value={filters.max_results}
            onChange={(e) =>
              setFilters({ max_results: Number(e.target.value) })
            }
            min={1}
            max={200}
            className="w-24 bg-gray-800 border border-gray-600 text-white text-sm rounded px-2 py-1.5"
          />
        </div>
      </div>

      {/* Actions */}
      <div className="p-4 border-t border-gray-700 space-y-2">
        <button
          onClick={() => runScan()}
          disabled={isLoading || filters.strategies.length === 0}
          className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-sky-600 hover:bg-sky-500 disabled:bg-gray-700 disabled:text-gray-500 text-white font-semibold rounded-lg transition-colors"
        >
          <ScanIcon size={18} />
          {isLoading ? "Scanning..." : "Run Scan"}
        </button>
        <button
          onClick={resetFilters}
          className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded-lg transition-colors"
        >
          <RotateCcw size={14} />
          Reset Filters
        </button>
      </div>
    </aside>
  );
};

interface SliderRowProps {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  tooltip?: string;
}

const SliderRow: React.FC<SliderRowProps> = ({
  label,
  value,
  onChange,
  min = 0,
  max = 100,
  tooltip,
}) => (
  <div>
    <div className="flex justify-between text-xs mb-1">
      <span className="text-gray-400">
        {label}
        {tooltip && <InfoTooltip content={tooltip} />}
      </span>
      <span className="text-gray-300 font-medium">{value}</span>
    </div>
    <input
      type="range"
      min={min}
      max={max}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full accent-sky-500"
    />
  </div>
);
