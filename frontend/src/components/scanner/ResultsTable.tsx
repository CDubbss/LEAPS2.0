import React, { useMemo, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
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
  scoreColor,
  scoreBackground,
  spreadTypeLabel,
  spreadTypeBadgeColor,
} from "@/utils/formatting";
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { InfoTooltip } from "@/components/ui/Tooltip";
import { TOOLTIPS } from "@/utils/tooltips";
import { TickerModal } from "@/components/ticker/TickerModal";

export const ResultsTable: React.FC = () => {
  const { result, selectedSpread, selectSpread } = useScannerStore();
  const [sorting, setSorting] = useState<SortingState>([
    { id: "ml_score", desc: true },
  ]);
  const [tickerItem, setTickerItem] = useState<RankedSpread | null>(null);

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
        size: 70,
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
              {val >= 9999 ? "Unlimited" : formatCurrency(val)}
            </span>
          );
        },
        size: 85,
      },
    ],
    []
  );

  const table = useReactTable({
    data: result?.results ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

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
    <div className="flex-1 overflow-auto">
      <table className="w-full text-sm border-collapse table-fixed">
        <thead className="bg-gray-800 sticky top-0 z-10">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((header) => (
                <th
                  key={header.id}
                  className={`px-3 py-2 text-left text-xs font-medium text-gray-400 uppercase tracking-wider border-b border-gray-700 cursor-pointer hover:text-gray-200 select-none${header.column.columnDef.meta?.mobileHidden ? " hidden lg:table-cell" : ""}`}
                  style={{ width: header.getSize() }}
                  onClick={header.column.getToggleSortingHandler()}
                >
                  <span className="flex items-center gap-1">
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
                </th>
              ))}
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
