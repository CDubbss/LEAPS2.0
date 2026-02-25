import React from "react";
import type { FundamentalData } from "@/types";
import { formatMarketCap, formatPct, scoreColor } from "@/utils/formatting";
import { Building2 } from "lucide-react";

interface Props {
  fundamentals: FundamentalData;
}

export const FundamentalsCard: React.FC<Props> = ({ fundamentals }) => {
  const f = fundamentals;

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Building2 size={18} className="text-orange-400" />
          <h3 className="text-sm font-semibold text-white">Fundamentals</h3>
        </div>
        {f.fundamental_score !== null && (
          <span className={`text-xl font-bold ${scoreColor(f.fundamental_score)}`}>
            {f.fundamental_score.toFixed(0)}
          </span>
        )}
      </div>

      <div className="text-xs text-gray-400">
        {f.company_name && <span className="text-gray-300">{f.company_name} · </span>}
        {f.sector && <span>{f.sector}</span>}
        {f.market_cap > 0 && (
          <span className="ml-2 text-gray-500">
            {formatMarketCap(f.market_cap)} mkt cap
          </span>
        )}
      </div>

      <div className="space-y-0.5">
        <FundRow label="P/E Ratio" value={f.pe_ratio?.toFixed(1)} />
        <FundRow label="Forward P/E" value={f.forward_pe?.toFixed(1)} />
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
        <FundRow label="Debt / Equity" value={f.debt_to_equity?.toFixed(2)} />
        <FundRow
          label="Gross Margin"
          value={f.gross_margin !== null ? formatPct(f.gross_margin) : null}
        />
        <FundRow
          label="Operating Margin"
          value={f.operating_margin !== null ? formatPct(f.operating_margin) : null}
        />
        <FundRow
          label="Return on Equity"
          value={f.return_on_equity !== null ? formatPct(f.return_on_equity) : null}
          colored
        />
        <FundRow
          label="FCF Yield"
          value={f.free_cash_flow_yield !== null ? formatPct(f.free_cash_flow_yield) : null}
          colored
        />
        {f.next_earnings_date && (
          <div className="flex justify-between items-center py-1 border-b border-gray-700/40">
            <span className="text-xs text-gray-400">Next Earnings</span>
            <span
              className={`text-xs font-medium ${
                (f.days_to_earnings ?? 999) < 14
                  ? "text-yellow-400"
                  : "text-gray-200"
              }`}
            >
              {f.next_earnings_date}
              {f.days_to_earnings !== null && (
                <span className="text-gray-500 ml-1">
                  ({f.days_to_earnings}d)
                </span>
              )}
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

const FundRow: React.FC<{
  label: string;
  value?: string | null;
  colored?: boolean;
}> = ({ label, value, colored = false }) => {
  if (value === null || value === undefined) return null;

  let colorClass = "text-gray-200";
  if (colored && value) {
    const num = parseFloat(value.replace(/%/g, "").replace(/,/g, ""));
    colorClass = num >= 0 ? "text-green-400" : "text-red-400";
  }

  return (
    <div className="flex justify-between items-center py-1 border-b border-gray-700/40">
      <span className="text-xs text-gray-400">{label}</span>
      <span className={`text-xs font-medium ${colorClass}`}>{value}</span>
    </div>
  );
};
