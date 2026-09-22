import React, { useState, useEffect } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useScannerStore } from "@/store/scannerStore";
import type { RankedSpread } from "@/types";
import { FilterPanel } from "@/components/scanner/FilterPanel";
import { ResultsTable } from "@/components/scanner/ResultsTable";
import { ScanSummaryBar } from "@/components/scanner/ScanSummaryBar";
import { CardShell } from "@/components/detail/CardShell";
import { SpreadDetailCard } from "@/components/detail/SpreadDetailCard";
import { MLScoreCard } from "@/components/detail/MLScoreCard";
import { SentimentScoreCard } from "@/components/detail/SentimentScoreCard";
import { RiskBreakdownCard } from "@/components/detail/RiskBreakdownCard";
import { FundamentalsCard } from "@/components/detail/FundamentalsCard";
import { Loader2, SlidersHorizontal, X } from "lucide-react";

/** Detail-panel cards. `id` matches DEFAULT_CARD_ORDER in the store; render() takes
 *  the selected spread. Reorder/expand is driven by the ids, not array position. */
const CARD_REGISTRY: Array<{
  id: string;
  title: string;
  render: (s: RankedSpread) => React.ReactNode;
}> = [
  { id: "spread", title: "Spread Details", render: (s) => <SpreadDetailCard item={s} /> },
  { id: "ml", title: "ML Analysis", render: (s) => <MLScoreCard prediction={s.ml_prediction} /> },
  { id: "sentiment", title: "News Sentiment", render: (s) => <SentimentScoreCard sentiment={s.sentiment} /> },
  { id: "risk", title: "Risk Breakdown", render: (s) => <RiskBreakdownCard riskScore={s.risk_score} /> },
  { id: "fundamentals", title: "Fundamentals", render: (s) => <FundamentalsCard fundamentals={s.fundamentals} /> },
];

export const ScannerPage: React.FC = () => {
  const {
    result, isLoading, error, selectedSpread, selectSpread,
    resumeActiveScan, loadPresets, cardOrder, setCardOrder,
  } = useScannerStore();
  const [filterOpen, setFilterOpen] = useState(false);

  // Detail-card reorder (native DnD, desktop) + expand-to-focus (modal).
  const [expandedCardId, setExpandedCardId] = useState<string | null>(null);
  const [dragCardId, setDragCardId] = useState<string | null>(null);
  const [dragOverCardId, setDragOverCardId] = useState<string | null>(null);

  // Auto-close filter drawer when scan starts
  useEffect(() => {
    if (isLoading) setFilterOpen(false);
  }, [isLoading]);

  // Reattach to a scan that was running when the page was closed/refreshed,
  // and pull server-side presets (durable across browsers/origins).
  useEffect(() => {
    void resumeActiveScan();
    void loadPresets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const orderedCards = cardOrder
    .map((id) => CARD_REGISTRY.find((c) => c.id === id))
    .filter((c): c is (typeof CARD_REGISTRY)[number] => !!c);

  const expandedCard = expandedCardId
    ? CARD_REGISTRY.find((c) => c.id === expandedCardId) ?? null
    : null;

  // Move `from` to just before `to` in the persisted card order.
  const moveCard = (from: string, to: string) => {
    if (from === to) return;
    const next = cardOrder.filter((id) => id !== from);
    const idx = next.indexOf(to);
    next.splice(idx < 0 ? next.length : idx, 0, from);
    setCardOrder(next);
  };

  const renderCards = () => {
    const s = selectedSpread;
    if (!s) return null;
    return (
      <div className="p-3 space-y-3">
        {orderedCards.map((card) => (
          <CardShell
            key={card.id}
            isDragging={dragCardId === card.id}
            isDragOver={dragOverCardId === card.id && dragCardId !== card.id}
            onExpand={() => setExpandedCardId(card.id)}
            onDragStart={() => setDragCardId(card.id)}
            onDragOver={(e) => {
              if (!dragCardId) return;
              e.preventDefault();
              if (dragOverCardId !== card.id) setDragOverCardId(card.id);
            }}
            onDrop={() => {
              if (dragCardId) moveCard(dragCardId, card.id);
              setDragCardId(null);
              setDragOverCardId(null);
            }}
            onDragEnd={() => {
              setDragCardId(null);
              setDragOverCardId(null);
            }}
          >
            {card.render(s)}
          </CardShell>
        ))}
      </div>
    );
  };

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

      {/* Mobile filter drawer (hidden on desktop) */}
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
            {renderCards()}
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
            {renderCards()}
          </div>
        </div>
      )}

      {/* Expand-to-focus modal — enlarges one card so its charts/detail are readable */}
      <Dialog.Root
        open={!!expandedCard && !!selectedSpread}
        onOpenChange={(open) => !open && setExpandedCardId(null)}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[92vw] max-w-2xl max-h-[88vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-xl border border-gray-700 bg-gray-900 shadow-2xl focus:outline-none">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 sticky top-0 bg-gray-900 z-10">
              <Dialog.Title className="text-sm font-semibold text-white">
                {expandedCard?.title}
                {selectedSpread && (
                  <span className="text-gray-500 font-normal ml-2">
                    {selectedSpread.spread.underlying} · Rank #{selectedSpread.rank}
                  </span>
                )}
              </Dialog.Title>
              <Dialog.Close className="text-gray-400 hover:text-white">
                <X size={16} />
              </Dialog.Close>
            </div>
            <Dialog.Description className="sr-only">
              Enlarged view of the {expandedCard?.title} detail card.
            </Dialog.Description>
            <div className="p-4">
              {expandedCard && selectedSpread && expandedCard.render(selectedSpread)}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

    </div>
  );
};
