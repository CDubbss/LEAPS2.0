/**
 * PositionsPage — tracks spreads the user has actually entered.
 *
 * Each open position is priced live (yfinance via backend) and compared
 * against the strategy exit rules:
 *   • TARGET HIT (green)  — P&L ≥ commission-adjusted +50% of debit → sell
 *   • STOP HIT   (red)    — P&L ≤ −25% of debit → cut the loss
 *
 * Add positions manually here, or via "Track" on a scanner result.
 * Mobile: table scrolls horizontally; pb-16 clears the BottomTabBar.
 */
import React, { useCallback, useEffect, useState } from "react";
import { positionsApi } from "@/api/client";
import type { Position, PositionCreate } from "@/api/client";
import { formatCurrency, formatDate } from "@/utils/formatting";
import { Loader2, Plus, RefreshCw, Trash2, X } from "lucide-react";

export const PositionsPage: React.FC = () => {
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const load = useCallback(async (refresh = true) => {
    setLoading(true);
    setError(null);
    try {
      setPositions(await positionsApi.list(refresh));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const open = positions.filter((p) => p.status === "open");
  const closed = positions.filter((p) => p.status === "closed");
  const totalPnl = open.reduce((s, p) => s + (p.pnl_dollars ?? 0), 0);
  const actionable = open.filter((p) => p.target_hit || p.stop_hit).length;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ── Header bar ─────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-900 border-b border-gray-700 flex-shrink-0">
        <span className="text-sm font-semibold text-white">Positions</span>
        <span className="text-xs text-gray-500">
          {open.length} open · {closed.length} closed
        </span>
        {open.length > 0 && (
          <span
            className={`text-xs font-mono font-semibold ${
              totalPnl >= 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            {totalPnl >= 0 ? "+" : ""}
            {formatCurrency(totalPnl)}
          </span>
        )}
        {actionable > 0 && (
          <span className="px-2 py-0.5 rounded bg-amber-600/30 text-amber-300 text-xs font-medium">
            {actionable} need action
          </span>
        )}
        <div className="ml-auto flex gap-2">
          <button
            onClick={() => void load()}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm rounded-lg font-medium transition-colors"
            title="Refresh live prices"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            <span className="hidden sm:inline">Refresh</span>
          </button>
          <button
            onClick={() => setShowAdd(true)}
            className="flex items-center gap-1.5 px-3 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded-lg font-medium transition-colors"
          >
            <Plus size={15} />
            <span className="hidden sm:inline">Add Position</span>
          </button>
        </div>
      </div>

      {/* ── Body ───────────────────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-auto pb-16 lg:pb-0">
        {loading && positions.length === 0 && (
          <div className="h-full flex items-center justify-center">
            <Loader2 size={32} className="text-sky-500 animate-spin" />
          </div>
        )}

        {error && (
          <div className="mx-3 mt-3 text-red-400 text-sm bg-red-900/20 border border-red-700 rounded-lg p-3">
            {error}
          </div>
        )}

        {!loading && positions.length === 0 && !error && (
          <div className="h-full flex flex-col items-center justify-center text-gray-500 text-sm gap-2">
            <span>No positions tracked yet.</span>
            <span>
              Add one here, or click "Track" on a scanner result.
            </span>
          </div>
        )}

        {open.length > 0 && (
          <PositionsTable
            title="Open"
            rows={open}
            onChanged={() => void load(false)}
          />
        )}
        {closed.length > 0 && (
          <PositionsTable
            title="Closed"
            rows={closed}
            onChanged={() => void load(false)}
          />
        )}
      </div>

      {showAdd && (
        <AddPositionDialog
          onClose={() => setShowAdd(false)}
          onAdded={() => {
            setShowAdd(false);
            void load();
          }}
        />
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Table
// ---------------------------------------------------------------------------

const PositionsTable: React.FC<{
  title: string;
  rows: Position[];
  onChanged: () => void;
}> = ({ title, rows, onChanged }) => {
  const th =
    "px-2 py-1.5 text-left text-[10px] font-semibold text-gray-400 uppercase tracking-wide whitespace-nowrap";
  const td = "px-2 py-2 text-xs whitespace-nowrap";

  const closePosition = async (p: Position) => {
    const raw = window.prompt(
      `Close ${p.symbol} — exit value per share (current: ${
        p.current_value != null ? p.current_value.toFixed(2) : "unknown"
      })`,
      p.current_value != null ? p.current_value.toFixed(2) : ""
    );
    if (raw == null) return;
    const exitValue = parseFloat(raw);
    if (isNaN(exitValue) || exitValue < 0) return;
    await positionsApi.update(p.id, { status: "closed", exit_value: exitValue });
    onChanged();
  };

  const deletePosition = async (p: Position) => {
    if (!window.confirm(`Delete ${p.symbol} position permanently?`)) return;
    await positionsApi.remove(p.id);
    onChanged();
  };

  const fixExpiration = async (p: Position) => {
    const raw = window.prompt(
      `Correct expiration for ${p.symbol} (YYYY-MM-DD). Options expire on Fridays — check your broker statement.`,
      p.expiration
    );
    if (!raw?.trim()) return;
    try {
      await positionsApi.update(p.id, { expiration: raw.trim() });
      onChanged();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Update failed");
    }
  };

  return (
    <div className="px-3 mt-3">
      <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-1.5">
        {title}
      </div>
      <div className="overflow-x-auto rounded-lg border border-gray-800">
        <table className="w-full border-collapse min-w-[720px]">
          <thead className="bg-gray-800/80">
            <tr>
              <th className={th}>Symbol</th>
              <th className={th}>Legs</th>
              <th className={th}>Exp</th>
              <th className={th}>Entry</th>
              <th className={th}>Now</th>
              <th className={th}>P&L</th>
              <th className={th}>Status</th>
              <th className={th}>Held</th>
              <th className={th}>DTE</th>
              <th className={th}>Ct</th>
              <th className={th}></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <PositionRow
                key={p.id}
                p={p}
                td={td}
                onClose={() => void closePosition(p)}
                onDelete={() => void deletePosition(p)}
                onFixDate={() => void fixExpiration(p)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const PositionRow: React.FC<{
  p: Position;
  td: string;
  onClose: () => void;
  onDelete: () => void;
  onFixDate: () => void;
}> = ({ p, td, onClose, onDelete, onFixDate }) => {
  const pnlColor =
    p.pnl_pct == null
      ? "text-gray-500"
      : p.pnl_pct >= 0
        ? "text-green-400"
        : "text-red-400";

  return (
    <tr className="border-t border-gray-800/60 hover:bg-gray-800/30">
      <td className={`${td} font-bold text-white`}>{p.symbol}</td>
      <td className={`${td} font-mono text-gray-300`}>
        {p.long_strike}
        {p.short_strike != null ? ` / ${p.short_strike}` : ""}{" "}
        <span className="text-gray-500">{p.long_option_type}</span>
      </td>
      <td className={`${td} text-gray-400`}>{formatDate(p.expiration)}</td>
      <td className={`${td} font-mono text-gray-300`}>
        {formatCurrency(p.entry_debit)}
      </td>
      <td className={`${td} font-mono text-gray-300`}>
        {p.current_value != null ? formatCurrency(p.current_value) : "—"}
      </td>
      <td className={`${td} font-mono font-semibold ${pnlColor}`}>
        {p.pnl_pct != null ? (
          <>
            {p.pnl_pct >= 0 ? "+" : ""}
            {p.pnl_pct.toFixed(1)}%
            {p.pnl_dollars != null && (
              <span className="text-gray-500 font-normal ml-1.5">
                ({p.pnl_dollars >= 0 ? "+" : ""}
                {formatCurrency(p.pnl_dollars)})
              </span>
            )}
          </>
        ) : (
          "—"
        )}
      </td>
      <td className={td}>
        <StatusBadge p={p} />
      </td>
      <td className={`${td} text-gray-400`}>{p.days_held}d</td>
      <td className={`${td} text-gray-400`}>{p.dte}</td>
      <td className={`${td} text-gray-400`}>{p.contracts}</td>
      <td className={`${td} text-right`}>
        <div className="flex gap-1 justify-end">
          {p.status === "open" && p.dte < 0 && (
            <button
              onClick={onFixDate}
              className="px-2 py-1 text-[10px] rounded bg-amber-700/60 hover:bg-amber-600/60 text-amber-100 font-medium whitespace-nowrap"
            >
              Fix date
            </button>
          )}
          {p.status === "open" && (
            <button
              onClick={onClose}
              className="px-2 py-1 text-[10px] rounded bg-gray-700 hover:bg-gray-600 text-gray-200 font-medium"
            >
              Close
            </button>
          )}
          <button
            onClick={onDelete}
            className="p-1 rounded text-gray-600 hover:text-red-400"
            title="Delete"
          >
            <Trash2 size={13} />
          </button>
        </div>
      </td>
    </tr>
  );
};

const StatusBadge: React.FC<{ p: Position }> = ({ p }) => {
  if (p.status === "closed") {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-gray-700 text-gray-300">
        CLOSED
      </span>
    );
  }
  if (p.dte < 0) {
    return (
      <span
        className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-900/40 text-red-300 border border-red-800"
        title="Expiration date is in the past — probably a typo. Use 'Fix date' to correct it."
      >
        EXPIRED?
      </span>
    );
  }
  // Ted (earnings IV-buildup) positions: the exit rule is time-based —
  // out before the print — not the +50%/−25% spread rules.
  if (p.spread_type.startsWith("ted") && p.exit_by) {
    const today = new Date().toISOString().slice(0, 10);
    const dayBefore = new Date(p.exit_by + "T12:00:00");
    dayBefore.setDate(dayBefore.getDate() - 1);
    const nearExit = today >= dayBefore.toISOString().slice(0, 10);
    if (today >= p.exit_by) {
      return (
        <span
          className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-600/30 text-red-300 border border-red-600"
          title={`Earnings ${p.earnings_date ?? "?"} — never hold through the print`}
        >
          EXIT NOW — PRINT RISK
        </span>
      );
    }
    return (
      <span
        className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${
          nearExit
            ? "bg-amber-600/25 text-amber-300 border-amber-600"
            : "bg-sky-900/40 text-sky-300 border-sky-800"
        }`}
        title={`Earnings ${p.earnings_date ?? "?"} — exit before the print`}
      >
        EXIT BY {p.exit_by.slice(5).replace("-", "/")}
      </span>
    );
  }
  if (p.target_hit) {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-600/30 text-green-300 border border-green-600">
        TARGET HIT — SELL
      </span>
    );
  }
  if (p.stop_hit) {
    return (
      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-600/30 text-red-300 border border-red-600">
        STOP HIT
      </span>
    );
  }
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-900/40 text-sky-300">
      HOLD → {p.target_pct.toFixed(0)}%
    </span>
  );
};

// ---------------------------------------------------------------------------
// Add-position dialog (plain fixed overlay — consistent with dark theme)
// ---------------------------------------------------------------------------

const emptyForm = (): PositionCreate => ({
  symbol: "",
  spread_type: "leaps_spread_call",
  long_strike: 0,
  long_option_type: "call",
  short_strike: null,
  short_option_type: null,
  expiration: "",
  entry_date: new Date().toISOString().slice(0, 10),
  entry_debit: 0,
  contracts: 10,
});

export const AddPositionDialog: React.FC<{
  initial?: Partial<PositionCreate>;
  onClose: () => void;
  onAdded: () => void;
}> = ({ initial, onClose, onAdded }) => {
  const [form, setForm] = useState<PositionCreate>({
    ...emptyForm(),
    ...initial,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (partial: Partial<PositionCreate>) =>
    setForm((f) => ({ ...f, ...partial }));

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      await positionsApi.create({
        ...form,
        symbol: form.symbol.toUpperCase().trim(),
        short_option_type:
          form.short_strike != null ? form.long_option_type : null,
      });
      onAdded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
      setSaving(false);
    }
  };

  const input =
    "w-full bg-gray-800 border border-gray-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500";
  const label = "block text-xs text-gray-400 mb-1";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-xl p-4 w-full max-w-md space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-white">
            Track a Position
          </span>
          <button onClick={onClose} className="text-gray-500 hover:text-white">
            <X size={18} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <span className={label}>Symbol</span>
            <input
              className={input}
              value={form.symbol}
              onChange={(e) => set({ symbol: e.target.value })}
              placeholder="AAPL"
            />
          </div>
          <div>
            <span className={label}>Expiration</span>
            <input
              className={input}
              type="date"
              value={form.expiration}
              onChange={(e) => set({ expiration: e.target.value })}
            />
          </div>
          <div>
            <span className={label}>Long strike</span>
            <input
              className={input}
              type="number"
              step="0.5"
              value={form.long_strike || ""}
              onChange={(e) => set({ long_strike: parseFloat(e.target.value) || 0 })}
            />
          </div>
          <div>
            <span className={label}>Short strike (blank = single leg)</span>
            <input
              className={input}
              type="number"
              step="0.5"
              value={form.short_strike ?? ""}
              onChange={(e) =>
                set({
                  short_strike: e.target.value === "" ? null : parseFloat(e.target.value),
                })
              }
            />
          </div>
          <div>
            <span className={label}>Entry date</span>
            <input
              className={input}
              type="date"
              value={form.entry_date}
              onChange={(e) => set({ entry_date: e.target.value })}
            />
          </div>
          <div>
            <span className={label}>Net debit / share</span>
            <input
              className={input}
              type="number"
              step="0.01"
              value={form.entry_debit || ""}
              onChange={(e) => set({ entry_debit: parseFloat(e.target.value) || 0 })}
            />
          </div>
          <div>
            <span className={label}>Contracts</span>
            <input
              className={input}
              type="number"
              min={1}
              value={form.contracts}
              onChange={(e) => set({ contracts: parseInt(e.target.value) || 1 })}
            />
          </div>
          <div>
            <span className={label}>Type</span>
            <select
              className={input}
              value={form.long_option_type}
              onChange={(e) => set({ long_option_type: e.target.value })}
            >
              <option value="call">Call</option>
              <option value="put">Put</option>
            </select>
          </div>
        </div>

        {error && <div className="text-red-400 text-xs">{error}</div>}

        <button
          onClick={() => void submit()}
          disabled={
            saving || !form.symbol || !form.expiration || form.entry_debit <= 0 || form.long_strike <= 0
          }
          className="w-full py-2 bg-sky-600 hover:bg-sky-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg font-medium transition-colors"
        >
          {saving ? "Saving..." : "Track Position"}
        </button>
      </div>
    </div>
  );
};
