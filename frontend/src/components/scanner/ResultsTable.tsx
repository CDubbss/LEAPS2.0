import React, { useMemo, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
  type OnChangeFn,
  type ColumnOrderState,
  type VisibilityState,
} from "@tanstack/react-table";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface ColumnMeta<TData, TValue> {
    mobileHidden?: boolean;
  }
}
import type { RankedSpread } from "@/types";
import { useScannerStore } from "@/store/scannerStore";
import {
  formatCurrency,
  formatDate,
  formatDTE,
  formatPct,
  formatScore,
  formatGreek,
  scoreColor,
  scoreBackground,
  spreadTypeLabel,
  spreadTypeBadgeColor,
} from "@/utils/formatting";
import { ArrowUpDown, ArrowUp, ArrowDown, GripVertical } from "lucide-react";
import { InfoTooltip } from "@/components/ui/Tooltip";
import { TOOLTIPS } from "@/utils/tooltips";
import { TickerModal } from "@/components/ticker/TickerModal";
import { ColumnPicker, type PickerColumn } from "@/components/scanner/ColumnPicker";

/** Human labels for the column picker (headers can be JSX, so we keep plain strings here). */
const COLUMN_LABELS: Record<string, string> = {
  rank: "Rank (#)",
  ticker: "Ticker",
  strategy: "Strategy",
  fit: "Fit",
  expiry: "Expiry",
  dte: "DTE",
  iv_rank: "IV Rank",
  pop: "PoP",
  ml_score: "ML Score",
  risk_score: "Risk",
  net_debit: "Debit",
  max_profit: "Max Profit",
  earnings: "Earnings",
  breakeven: "Breakeven",
  spread_width: "Spread Width",
  max_loss: "Max Loss",
  bid_ask_quality: "Bid-Ask Quality",
  expected_return: "Est. Return",
  confidence: "ML Confidence",
  fundamental: "Fundamental",
  sentiment: "Sentiment",
  delta: "Long Δ",
  oi: "Open Interest",
  volume: "Volume",
  sector: "Sector",
};

/**
 * Strategy-fit checks — mirrors the user's vertical LEAPS spread rules.
 * Returns the list of failed checks (empty = full fit).
 */
const strategyFitIssues = (r: RankedSpread): string[] => {
  const { spread } = r;
  const long = spread.long_leg;
  const issues: string[] = [];

  // 25% cost rule (two-leg spreads only; single-leg LEAPS exempt)
  if (spread.spread_width > 0 && spread.net_debit / spread.spread_width > 0.2501) {
    issues.push(
      `Cost ${((spread.net_debit / spread.spread_width) * 100).toFixed(0)}% of width (max 25%)`
    );
  }
  if (Math.abs(long.delta) > 0.33) {
    issues.push(`Delta ${Math.abs(long.delta).toFixed(2)} (max 0.33)`);
  }
  if (long.open_interest < 50) {
    issues.push(`OI ${long.open_interest} (min 50)`);
  }
  if (long.volume < 10) {
    issues.push(`Volume ${long.volume} (min 10)`);
  }
  const mid = (long.bid + long.ask) / 2;
  if (mid > 0 && (long.ask - long.bid) / mid > 0.25) {
    issues.push(
      `Bid-ask ${(((long.ask - long.bid) / mid) * 100).toFixed(0)}% (max 25%)`
    );
  }
  return issues;
};

export const ResultsTable: React.FC = () => {
  const {
    result,
    selectedSpread,
    selectSpread,
    columnOrder,
    columnVisibility,
    setColumnOrder,
    setColumnVisibility,
    resetColumns,
  } = useScannerStore();
  const [sorting, setSorting] = useState<SortingState>([
    { id: "ml_score", desc: true },
  ]);
  const [tickerItem, setTickerItem] = useState<RankedSpread | null>(null);
  // Native drag-and-drop column reorder (desktop only).
  const [dragCol, setDragCol] = useState<string | null>(null);
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);

  const columns = useMemo<ColumnDef<RankedSpread>[]>(
    () => [
      {
        id: "rank",
        header: "#",
        accessorFn: (r) => r.rank,
        cell: (info) => (
          <span className="text-gray-400 text-xs font-mono">
            {info.getValue() as number}
          </span>
        ),
        size: 40,
      },
      {
        id: "ticker",
        header: "Ticker",
        accessorFn: (r) => r.spread.underlying,
        cell: (info) => (
          <button
            className="font-bold text-sky-400 hover:text-sky-300 hover:underline block truncate w-full text-left"
            onClick={(e) => { e.stopPropagation(); setTickerItem(info.row.original); }}
          >
            {info.getValue() as string}
          </button>
        ),
        size: 70,
      },
      {
        id: "strategy",
        header: "Strategy",
        accessorFn: (r) => r.spread.spread_type,
        cell: (info) => (
          <span
            className={`px-2 py-0.5 rounded text-xs font-medium ${spreadTypeBadgeColor(
              info.getValue() as string
            )}`}
          >
            {spreadTypeLabel(info.getValue() as string)}
          </span>
        ),
        size: 100,
      },
      {
        id: "fit",
        header: () => (
          <span>
            Fit <InfoTooltip content="Strategy fit: 25% cost rule, delta ≤ 0.33, OI ≥ 50, volume ≥ 10, bid-ask ≤ 25%. Hover a badge to see which checks failed." />
          </span>
        ),
        accessorFn: (r) => strategyFitIssues(r).length,
        cell: (info) => {
          const issues = strategyFitIssues(info.row.original);
          return issues.length === 0 ? (
            <span
              className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-600/30 text-green-300 border border-green-700"
              title="Passes all strategy checks"
            >
              FIT
            </span>
          ) : (
            <span
              className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-600/20 text-amber-300 border border-amber-700/60"
              title={issues.join("\n")}
            >
              {issues.length} ✗
            </span>
          );
        },
        size: 55,
      },
      {
        id: "expiry",
        header: "Expiry",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.expiration,
        cell: (info) => (
          <span className="text-gray-300 text-xs">
            {formatDate(info.getValue() as string)}
          </span>
        ),
        size: 95,
      },
      {
        id: "dte",
        header: () => <span>DTE <InfoTooltip content={TOOLTIPS.dte_col} /></span>,
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.dte,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {formatDTE(info.getValue() as number)}
          </span>
        ),
        size: 55,
      },
      {
        id: "iv_rank",
        header: () => <span>IV Rank <InfoTooltip content={TOOLTIPS.iv_rank_col} /></span>,
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.iv_rank,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {formatScore(info.getValue() as number)}
          </span>
        ),
        size: 70,
      },
      {
        id: "pop",
        header: () => <span>PoP <InfoTooltip content={TOOLTIPS.pop_col} /></span>,
        accessorFn: (r) => r.spread.probability_of_profit,
        cell: (info) => (
          <span className="text-gray-200 text-xs font-mono">
            {formatPct(info.getValue() as number, 0)}
          </span>
        ),
        size: 55,
      },
      {
        id: "ml_score",
        header: () => <span>ML Score <InfoTooltip content={TOOLTIPS.ml_col} /></span>,
        accessorFn: (r) => r.ml_prediction.spread_quality_score,
        cell: (info) => {
          const score = info.getValue() as number;
          return (
            <div className="flex items-center gap-2">
              <div className="w-16 bg-gray-700 rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full ${scoreBackground(score)}`}
                  style={{ width: `${score}%` }}
                />
              </div>
              <span className={`text-xs font-bold ${scoreColor(score)}`}>
                {score.toFixed(0)}
              </span>
            </div>
          );
        },
        size: 120,
      },
      {
        id: "risk_score",
        header: () => <span>Risk <InfoTooltip content={TOOLTIPS.risk_col} /></span>,
        meta: { mobileHidden: true },
        accessorFn: (r) => r.risk_score.composite_score,
        cell: (info) => {
          const score = info.getValue() as number;
          return (
            <span className={`text-xs font-bold ${scoreColor(score)}`}>
              {score.toFixed(0)}
            </span>
          );
        },
        size: 55,
      },
      {
        id: "net_debit",
        header: "Debit",
        accessorFn: (r) => r.spread.net_debit,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {formatCurrency(info.getValue() as number)}
          </span>
        ),
        size: 80,
      },
      {
        id: "max_profit",
        header: "Max Profit",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.max_profit,
        cell: (info) => {
          const val = info.getValue() as number;
          return (
            <span className="text-green-400 text-xs font-mono">
              {val >= 9999 ? "Unlimited" : formatCurrency(val * 100)}
            </span>
          );
        },
        size: 90,
      },
      {
        id: "earnings",
        header: () => <span>Earnings</span>,
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.days_to_earnings,
        cell: (info) => {
          const days = info.getValue() as number | null;
          const row = info.row.original;
          if (days == null || days < 0) return <span className="text-gray-600 text-xs">—</span>;
          const urgencyColor =
            days <= 20
              ? "text-red-400"
              : days <= 35
              ? "text-amber-400"
              : "text-gray-400";
          return (
            <span className={`text-xs font-mono ${urgencyColor}`} title={row.spread.next_earnings_date ?? undefined}>
              {days}d
            </span>
          );
        },
        size: 70,
      },

      // ── Opt-in columns (hidden by default; mobileHidden so they never crowd the
      //    narrow mobile table even when a desktop layout enables them) ──
      {
        id: "breakeven",
        header: "Breakeven",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.breakeven,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {formatCurrency(info.getValue() as number)}
          </span>
        ),
        size: 90,
      },
      {
        id: "spread_width",
        header: "Width",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.spread_width,
        cell: (info) => {
          const w = info.getValue() as number;
          return (
            <span className="text-gray-300 text-xs font-mono">
              {w > 0 ? formatCurrency(w) : "—"}
            </span>
          );
        },
        size: 70,
      },
      {
        id: "max_loss",
        header: "Max Loss",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.max_loss,
        cell: (info) => (
          <span className="text-red-400 text-xs font-mono">
            {formatCurrency((info.getValue() as number) * 100)}
          </span>
        ),
        size: 90,
      },
      {
        id: "bid_ask_quality",
        header: "B/A Qual",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.bid_ask_quality_score,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {((info.getValue() as number) * 100).toFixed(0)}%
          </span>
        ),
        size: 70,
      },
      {
        id: "expected_return",
        header: "Est. Return",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.ml_prediction.expected_return_pct,
        cell: (info) => {
          const v = info.getValue() as number;
          return (
            <span className={`text-xs font-mono ${v >= 0 ? "text-green-400" : "text-red-400"}`}>
              {v >= 0 ? "+" : ""}{v.toFixed(0)}%
            </span>
          );
        },
        size: 80,
      },
      {
        id: "confidence",
        header: "Conf.",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.ml_prediction.confidence,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {((info.getValue() as number) * 100).toFixed(0)}%
          </span>
        ),
        size: 60,
      },
      {
        id: "fundamental",
        header: "Fund.",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.fundamentals.fundamental_score ?? -1,
        cell: (info) => {
          const v = info.getValue() as number;
          return v < 0 ? (
            <span className="text-gray-600 text-xs">—</span>
          ) : (
            <span className={`text-xs font-bold ${scoreColor(v)}`}>{v.toFixed(0)}</span>
          );
        },
        size: 60,
      },
      {
        id: "sentiment",
        header: "Sent.",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.sentiment.sentiment_score,
        cell: (info) => {
          const v = info.getValue() as number;
          return <span className={`text-xs font-bold ${scoreColor(v)}`}>{v.toFixed(0)}</span>;
        },
        size: 60,
      },
      {
        id: "delta",
        header: () => <span>Δ <InfoTooltip content={TOOLTIPS.delta} /></span>,
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.long_leg.delta,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {formatGreek(info.getValue() as number, 2)}
          </span>
        ),
        size: 60,
      },
      {
        id: "oi",
        header: "OI",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.long_leg.open_interest,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {(info.getValue() as number).toLocaleString()}
          </span>
        ),
        size: 70,
      },
      {
        id: "volume",
        header: "Vol",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.spread.long_leg.volume,
        cell: (info) => (
          <span className="text-gray-300 text-xs font-mono">
            {(info.getValue() as number).toLocaleString()}
          </span>
        ),
        size: 70,
      },
      {
        id: "sector",
        header: "Sector",
        meta: { mobileHidden: true },
        accessorFn: (r) => r.fundamentals.sector,
        cell: (info) => (
          <span className="text-gray-400 text-xs truncate block">
            {(info.getValue() as string) || "—"}
          </span>
        ),
        size: 120,
      },
    ],
    []
  );

  // Resolve TanStack's updater against the *live* store state (not the render-time
  // closure) so rapid successive toggles don't clobber one another.
  const handleColumnOrderChange: OnChangeFn<ColumnOrderState> = (updater) =>
    setColumnOrder(
      typeof updater === "function"
        ? updater(useScannerStore.getState().columnOrder)
        : updater
    );
  const handleColumnVisibilityChange: OnChangeFn<VisibilityState> = (updater) =>
    setColumnVisibility(
      typeof updater === "function"
        ? updater(useScannerStore.getState().columnVisibility)
        : updater
    );

  const table = useReactTable({
    data: result?.results ?? [],
    columns,
    state: { sorting, columnOrder, columnVisibility },
    onSortingChange: setSorting,
    onColumnOrderChange: handleColumnOrderChange,
    onColumnVisibilityChange: handleColumnVisibilityChange,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  // Move `from` to just before `to` within the full (incl. hidden) column order.
  const moveColumn = (from: string, to: string) => {
    if (!from || from === to) return;
    const next = columnOrder.filter((id) => id !== from);
    const idx = next.indexOf(to);
    next.splice(idx < 0 ? next.length : idx, 0, from);
    setColumnOrder(next);
  };

  const pickerColumns: PickerColumn[] = table.getAllLeafColumns().map((col) => ({
    id: col.id,
    label: COLUMN_LABELS[col.id] ?? col.id,
    isVisible: col.getIsVisible(),
  }));

  if (!result) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500">
        <div className="text-center">
          <p className="text-lg mb-2">No scan results yet</p>
          <p className="text-sm">Configure filters and click "Run Scan"</p>
        </div>
      </div>
    );
  }

  if (result.results.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-500">
        <div className="text-center">
          <p className="text-lg mb-2">No results found</p>
          <p className="text-sm">Try relaxing your filter criteria</p>
        </div>
      </div>
    );
  }

  return (
    <>
    {/* Column toolbar — desktop only */}
    <div className="hidden lg:flex items-center justify-end gap-2 px-3 py-1.5 border-b border-gray-800 bg-gray-900/40 flex-shrink-0">
      <ColumnPicker
        columns={pickerColumns}
        onToggle={(id) => table.getColumn(id)?.toggleVisibility()}
        onReset={resetColumns}
      />
    </div>

    <div className="flex-1 overflow-auto">
      <table className="min-w-full text-sm border-collapse table-fixed">
        <thead className="bg-gray-800 sticky top-0 z-10">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((header) => {
                const colId = header.column.id;
                return (
                <th
                  key={header.id}
                  className={`px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase tracking-wider border-b border-gray-700 select-none${header.column.columnDef.meta?.mobileHidden ? " hidden lg:table-cell" : ""}${dragOverCol === colId && dragCol && dragCol !== colId ? " bg-sky-900/30" : ""}${dragCol === colId ? " opacity-50" : ""}`}
                  style={{ width: header.getSize() }}
                  onDragOver={(e) => {
                    if (!dragCol) return;
                    e.preventDefault();
                    e.dataTransfer.dropEffect = "move";
                    if (dragOverCol !== colId) setDragOverCol(colId);
                  }}
                  onDragLeave={() => setDragOverCol((c) => (c === colId ? null : c))}
                  onDrop={() => {
                    if (dragCol) moveColumn(dragCol, colId);
                    setDragCol(null);
                    setDragOverCol(null);
                  }}
                >
                  <span className="flex items-center gap-1">
                    <span
                      draggable
                      onDragStart={(e) => {
                        setDragCol(colId);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onDragEnd={() => {
                        setDragCol(null);
                        setDragOverCol(null);
                      }}
                      onClick={(e) => e.stopPropagation()}
                      title="Drag to reorder column"
                      className="hidden lg:inline-flex cursor-grab active:cursor-grabbing text-gray-600 hover:text-gray-300 -ml-1"
                    >
                      <GripVertical size={11} />
                    </span>
                    <span
                      className="flex items-center gap-1 cursor-pointer hover:text-gray-200"
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext()
                      )}
                      {header.column.getIsSorted() === "asc" ? (
                        <ArrowUp size={10} />
                      ) : header.column.getIsSorted() === "desc" ? (
                        <ArrowDown size={10} />
                      ) : (
                        <ArrowUpDown size={10} className="opacity-40" />
                      )}
                    </span>
                  </span>
                </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => {
            const isSelected =
              selectedSpread?.spread.underlying === row.original.spread.underlying &&
              selectedSpread?.spread.expiration === row.original.spread.expiration &&
              selectedSpread?.spread.spread_type === row.original.spread.spread_type;

            return (
              <tr
                key={row.id}
                onClick={() =>
                  selectSpread(isSelected ? null : row.original)
                }
                className={`border-b border-gray-800 cursor-pointer transition-colors ${
                  isSelected
                    ? "bg-sky-900/40 border-sky-700"
                    : "hover:bg-gray-800/60"
                }`}
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className={`px-3 py-2 max-w-0 overflow-hidden${cell.column.columnDef.meta?.mobileHidden ? " hidden lg:table-cell" : ""}`}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>

    {tickerItem && (
      <TickerModal item={tickerItem} onClose={() => setTickerItem(null)} />
    )}
    </>
  );
};
