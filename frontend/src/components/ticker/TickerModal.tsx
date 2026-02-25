import React from "react";
import * as Dialog from "@radix-ui/react-dialog";
import type { RankedSpread } from "@/types";
import { CandlestickChart } from "./CandlestickChart";
import { formatMarketCap, formatPct, scoreColor } from "@/utils/formatting";
import { X, Building2 } from "lucide-react";

interface Props {
  item: RankedSpread;
  onClose: () => void;
}

export const TickerModal: React.FC<Props> = ({ item, onClose }) => {
  const f = item.fundamentals;
  const symbol = item.spread.underlying;

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/60 z-40" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50
                     bg-gray-900 border border-gray-700 rounded-xl shadow-2xl
                     w-[min(90vw,760px)] max-h-[85vh] overflow-y-auto"
        >
          {/* Header */}
          <div className="flex items-start justify-between p-5 border-b border-gray-700">
            <div>
              <div className="flex items-center gap-3">
                <Dialog.Title className="text-2xl font-bold text-white">{symbol}</Dialog.Title>
                {f.fundamental_score !== null && (
                  <span className={`text-sm font-semibold px-2 py-0.5 rounded bg-gray-700 ${scoreColor(f.fundamental_score)}`}>
                    Score {f.fundamental_score.toFixed(0)}
                  </span>
                )}
              </div>
              <Dialog.Description className="text-sm text-gray-400 mt-1">
                {[f.company_name, f.sector, f.industry].filter(Boolean).join(" · ")}
                {f.market_cap > 0 && (
                  <span className="ml-2 text-gray-500">· {formatMarketCap(f.market_cap)} mkt cap</span>
                )}
              </Dialog.Description>
            </div>
            <button
              onClick={onClose}
              className="text-gray-500 hover:text-gray-300 transition-colors mt-1"
            >
              <X size={20} />
            </button>
          </div>

          <div className="p-5 space-y-5">
            {/* Candlestick chart */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <span className="text-sm font-semibold text-white">Price History</span>
              </div>
              <CandlestickChart symbol={symbol} />
            </div>

            {/* Fundamentals grid */}
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Building2 size={16} className="text-orange-400" />
                <span className="text-sm font-semibold text-white">Fundamentals</span>
              </div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-0">
                <FundRow label="P/E Ratio" value={f.pe_ratio?.toFixed(1)} />
                <FundRow label="Forward P/E" value={f.forward_pe?.toFixed(1)} />
                <FundRow label="PEG Ratio" value={f.peg_ratio?.toFixed(2)} />
                <FundRow label="Price / Book" value={f.price_to_book?.toFixed(2)} />
                <FundRow label="Price / Sales" value={f.price_to_sales?.toFixed(2)} />
                <FundRow label="Debt / Equity" value={f.debt_to_equity?.toFixed(2)} />
                <FundRow label="Current Ratio" value={f.current_ratio?.toFixed(2)} />
                <FundRow
                  label="Revenue Growth"
                  value={f.revenue_growth_yoy !== null ? formatPct(f.revenue_growth_yoy) : null}
                  colored
                />
                <FundRow
                  label="Earnings Growth"
                  value={f.earnings_growth_yoy !== null ? formatPct(f.earnings_growth_yoy) : null}
                  colored
                />
                <FundRow
                  label="Gross Margin"
                  value={f.gross_margin !== null ? formatPct(f.gross_margin) : null}
                />
                <FundRow
                  label="Operating Margin"
                  value={f.operating_margin !== null ? formatPct(f.operating_margin) : null}
                />
                <FundRow
                  label="Net Margin"
                  value={f.net_margin !== null ? formatPct(f.net_margin) : null}
                />
                <FundRow
                  label="Return on Equity"
                  value={f.return_on_equity !== null ? formatPct(f.return_on_equity) : null}
                  colored
                />
                <FundRow
                  label="Return on Assets"
                  value={f.return_on_assets !== null ? formatPct(f.return_on_assets) : null}
                  colored
                />
                <FundRow
                  label="FCF Yield"
                  value={f.free_cash_flow_yield !== null ? formatPct(f.free_cash_flow_yield) : null}
                  colored
                />
                {f.next_earnings_date && (
                  <FundRow
                    label="Next Earnings"
                    value={`${f.next_earnings_date}${f.days_to_earnings !== null ? ` (${f.days_to_earnings}d)` : ""}`}
                    warn={(f.days_to_earnings ?? 999) < 14}
                  />
                )}
              </div>
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
};

const FundRow: React.FC<{
  label: string;
  value?: string | null;
  colored?: boolean;
  warn?: boolean;
}> = ({ label, value, colored = false, warn = false }) => {
  if (value === null || value === undefined) return null;

  let colorClass = "text-gray-200";
  if (warn) {
    colorClass = "text-yellow-400";
  } else if (colored && value) {
    const num = parseFloat(value.replace(/%/g, "").replace(/,/g, ""));
    colorClass = num >= 0 ? "text-green-400" : "text-red-400";
  }

  return (
    <div className="flex justify-between items-center py-1.5 border-b border-gray-700/40">
      <span className="text-xs text-gray-400">{label}</span>
      <span className={`text-xs font-medium ${colorClass}`}>{value}</span>
    </div>
  );
};
