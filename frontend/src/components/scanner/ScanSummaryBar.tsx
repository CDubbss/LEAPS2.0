import React from "react";
import type { RankedSpread, ScannerResult } from "@/types";
import { formatDate } from "@/utils/formatting";
import { Clock, BarChart2, CheckCircle, Download } from "lucide-react";

interface Props {
  result: ScannerResult;
}

/** Escape a CSV field per RFC 4180. */
const csvField = (v: unknown): string => {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

const CSV_COLUMNS: [string, (r: RankedSpread) => unknown][] = [
  ["rank", (r) => r.rank],
  ["underlying", (r) => r.spread.underlying],
  ["strategy", (r) => r.spread.spread_type],
  ["expiration", (r) => r.spread.expiration],
  ["dte", (r) => r.spread.dte],
  ["long_strike", (r) => r.spread.long_leg.strike],
  ["short_strike", (r) => r.spread.short_leg?.strike ?? ""],
  ["net_debit", (r) => r.spread.net_debit],
  ["spread_width", (r) => r.spread.spread_width],
  ["max_profit", (r) => r.spread.max_profit],
  ["breakeven", (r) => r.spread.breakeven],
  ["long_delta", (r) => r.spread.long_leg.delta],
  ["iv_rank", (r) => r.spread.iv_rank],
  ["pop", (r) => r.spread.probability_of_profit],
  ["ml_score", (r) => r.ml_prediction.spread_quality_score.toFixed(2)],
  ["risk_score", (r) => r.risk_score.composite_score],
  ["volume", (r) => r.spread.long_leg.volume],
  ["open_interest", (r) => r.spread.long_leg.open_interest],
  ["days_to_earnings", (r) => r.spread.days_to_earnings ?? ""],
];

const exportCsv = (result: ScannerResult) => {
  const header = CSV_COLUMNS.map(([name]) => name).join(",");
  const lines = result.results.map((r) =>
    CSV_COLUMNS.map(([, get]) => csvField(get(r))).join(",")
  );
  const blob = new Blob([header + "\n" + lines.join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `leaps-scan-${result.scan_time.slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(url);
};

export const ScanSummaryBar: React.FC<Props> = ({ result }) => {
  return (
    <div className="flex items-center gap-6 px-4 py-3 bg-gray-800 border-b border-gray-700 text-sm">
      <div className="flex items-center gap-2 text-gray-300">
        <BarChart2 size={16} className="text-sky-400" />
        <span>
          <span className="text-white font-semibold">
            {result.total_candidates_evaluated.toLocaleString()}
          </span>{" "}
          candidates evaluated
        </span>
      </div>
      <div className="flex items-center gap-2 text-gray-300">
        <CheckCircle size={16} className="text-green-400" />
        <span>
          <span className="text-white font-semibold">
            {result.results.length}
          </span>{" "}
          passed filters
        </span>
      </div>
      <div className="flex items-center gap-2 text-gray-300">
        <Clock size={16} className="text-gray-400" />
        <span>{result.scan_duration_seconds.toFixed(1)}s</span>
      </div>
      <div className="ml-auto flex items-center gap-3">
        <button
          onClick={() => exportCsv(result)}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-200 text-xs font-medium transition-colors"
          title="Export results to CSV"
        >
          <Download size={13} />
          CSV
        </button>
        <span className="text-gray-500 text-xs">
          Scanned {formatDate(result.scan_time)}
        </span>
      </div>
    </div>
  );
};
