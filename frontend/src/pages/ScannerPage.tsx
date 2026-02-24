import React from "react";
import { useScannerStore } from "@/store/scannerStore";
import { FilterPanel } from "@/components/scanner/FilterPanel";
import { ResultsTable } from "@/components/scanner/ResultsTable";
import { ScanSummaryBar } from "@/components/scanner/ScanSummaryBar";
import { SpreadDetailCard } from "@/components/detail/SpreadDetailCard";
import { MLScoreCard } from "@/components/detail/MLScoreCard";
import { SentimentScoreCard } from "@/components/detail/SentimentScoreCard";
import { RiskBreakdownCard } from "@/components/detail/RiskBreakdownCard";
import { FundamentalsCard } from "@/components/detail/FundamentalsCard";
import { Loader2 } from "lucide-react";

export const ScannerPage: React.FC = () => {
  const { result, isLoading, error, selectedSpread } = useScannerStore();

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left: Filter Panel */}
      <FilterPanel />

      {/* Center: Results */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Summary bar */}
        {result && <ScanSummaryBar result={result} />}

        {/* Loading state */}
        {isLoading && (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center space-y-3">
              <Loader2
                size={48}
                className="text-sky-500 animate-spin mx-auto"
              />
              <p className="text-gray-300 font-medium">Scanning options market...</p>
              <p className="text-gray-500 text-sm">
                Fetching chains · scoring sentiment · running ML inference
              </p>
            </div>
          </div>
        )}

        {/* Error state */}
        {!isLoading && error && (
          <div className="flex-1 flex items-center justify-center p-8">
            <div className="bg-red-900/30 border border-red-700 rounded-lg p-6 max-w-md text-center">
              <p className="text-red-400 font-semibold mb-2">Scan Failed</p>
              <p className="text-red-300/80 text-sm">{error}</p>
              <p className="text-gray-500 text-xs mt-3">
                Ensure the backend is running at localhost:8000
              </p>
            </div>
          </div>
        )}

        {/* Results table */}
        {!isLoading && !error && <ResultsTable />}
      </div>

      {/* Right: Detail Panel (shown when a spread is selected) */}
      {selectedSpread && (
        <aside className="w-80 bg-gray-900 border-l border-gray-700 overflow-y-auto flex-shrink-0">
          <div className="p-3 border-b border-gray-700">
            <h2 className="text-sm font-semibold text-white">
              Spread Details — Rank #{selectedSpread.rank}
            </h2>
          </div>
          <div className="p-3 space-y-3">
            <SpreadDetailCard item={selectedSpread} />
            <MLScoreCard prediction={selectedSpread.ml_prediction} />
            <SentimentScoreCard sentiment={selectedSpread.sentiment} />
            <RiskBreakdownCard riskScore={selectedSpread.risk_score} />
            <FundamentalsCard fundamentals={selectedSpread.fundamentals} />
          </div>
        </aside>
      )}
    </div>
  );
};
