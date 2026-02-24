import React, { useState, useEffect } from "react";
import { useScannerStore } from "@/store/scannerStore";
import { FilterPanel } from "@/components/scanner/FilterPanel";
import { ResultsTable } from "@/components/scanner/ResultsTable";
import { ScanSummaryBar } from "@/components/scanner/ScanSummaryBar";
import { SpreadDetailCard } from "@/components/detail/SpreadDetailCard";
import { MLScoreCard } from "@/components/detail/MLScoreCard";
import { SentimentScoreCard } from "@/components/detail/SentimentScoreCard";
import { RiskBreakdownCard } from "@/components/detail/RiskBreakdownCard";
import { FundamentalsCard } from "@/components/detail/FundamentalsCard";
import { Loader2, SlidersHorizontal, X } from "lucide-react";

export const ScannerPage: React.FC = () => {
  const { result, isLoading, error, selectedSpread, selectSpread } = useScannerStore();
  const [filterOpen, setFilterOpen] = useState(false);

  // Auto-close filter drawer when scan starts
  useEffect(() => {
    if (isLoading) setFilterOpen(false);
  }, [isLoading]);

  const detailContent = selectedSpread && (
    <div className="p-3 space-y-3">
      <SpreadDetailCard item={selectedSpread} />
      <MLScoreCard prediction={selectedSpread.ml_prediction} />
      <SentimentScoreCard sentiment={selectedSpread.sentiment} />
      <RiskBreakdownCard riskScore={selectedSpread.risk_score} />
      <FundamentalsCard fundamentals={selectedSpread.fundamentals} />
    </div>
  );

  return (
    <div className="flex flex-col h-full overflow-hidden">

      {/* Mobile toolbar (hidden on desktop) */}
      <div className="lg:hidden flex items-center gap-2 px-3 py-2 border-b border-gray-700 bg-gray-900 flex-shrink-0">
        <button
          onClick={() => setFilterOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600 rounded text-sm text-white transition-colors"
        >
          <SlidersHorizontal size={14} />
          Filters
        </button>
        {result && (
          <span className="text-xs text-gray-500 ml-auto">
            {result.results.length} results
          </span>
        )}
      </div>

      {/* Mobile filter drawer */}
      {filterOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/60" onClick={() => setFilterOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-80 bg-gray-900 flex flex-col overflow-y-auto shadow-xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 flex-shrink-0">
              <span className="text-sm font-semibold text-white">Filters</span>
              <button onClick={() => setFilterOpen(false)} className="text-gray-400 hover:text-white">
                <X size={16} />
              </button>
            </div>
            <FilterPanel />
          </div>
        </div>
      )}

      {/* Main content row */}
      <div className="flex flex-1 overflow-hidden">

        {/* Desktop filter sidebar (hidden on mobile) */}
        <div className="hidden lg:flex flex-col w-72 flex-shrink-0 border-r border-gray-700 overflow-y-auto bg-gray-900">
          <FilterPanel />
        </div>

        {/* Center: Results */}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">
          {result && <ScanSummaryBar result={result} />}

          {isLoading && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center space-y-3">
                <Loader2 size={48} className="text-sky-500 animate-spin mx-auto" />
                <p className="text-gray-300 font-medium">Scanning options market...</p>
                <p className="text-gray-500 text-sm">
                  Fetching chains · scoring sentiment · running ML inference
                </p>
              </div>
            </div>
          )}

          {!isLoading && error && (
            <div className="flex-1 flex items-center justify-center p-8">
              <div className="bg-red-900/30 border border-red-700 rounded-lg p-6 max-w-md text-center">
                <p className="text-red-400 font-semibold mb-2">Scan Failed</p>
                <p className="text-red-300/80 text-sm">{error}</p>
                <p className="text-gray-500 text-xs mt-3">
                  Ensure the backend is running at localhost:8001
                </p>
              </div>
            </div>
          )}

          {!isLoading && !error && <ResultsTable />}
        </div>

        {/* Desktop detail panel (hidden on mobile) */}
        {selectedSpread && (
          <aside className="hidden lg:flex flex-col w-96 bg-gray-900 border-l border-gray-700 overflow-y-auto flex-shrink-0">
            <div className="p-3 border-b border-gray-700">
              <h2 className="text-sm font-semibold text-white">
                Spread Details — Rank #{selectedSpread.rank}
              </h2>
            </div>
            {detailContent}
          </aside>
        )}
      </div>

      {/* Mobile detail bottom sheet (hidden on desktop) */}
      {selectedSpread && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/60" onClick={() => selectSpread(null)} />
          <div className="absolute bottom-0 left-0 right-0 max-h-[85vh] bg-gray-900 rounded-t-2xl overflow-y-auto shadow-xl">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 sticky top-0 bg-gray-900 rounded-t-2xl">
              <h2 className="text-sm font-semibold text-white">
                Spread Details — Rank #{selectedSpread.rank}
              </h2>
              <button onClick={() => selectSpread(null)} className="text-gray-400 hover:text-white">
                <X size={16} />
              </button>
            </div>
            {detailContent}
          </div>
        </div>
      )}

    </div>
  );
};
