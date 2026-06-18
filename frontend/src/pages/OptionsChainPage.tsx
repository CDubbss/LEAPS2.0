/**
 * OptionsChainPage — options chain viewer.
 *
 * Mobile layout:
 *   • Symbol search bar full-width with a compact "Load" button.
 *   • Expiration pills scroll horizontally.
 *   • Chain table: sticky strike column so it's always visible while scrolling.
 *   • ATM row highlighted and auto-scrolled into view on load.
 *   • pb-16 clears the BottomTabBar.
 *
 * Desktop layout: same, but with more horizontal space so scrolling is minimal.
 *
 * To restyle:
 *   • Column colors: change headerCls / cellCls strings in OptionsChainTable.
 *   • ATM highlight: change the bg-sky-900/20 class on the ATM row.
 *   • Input/button: change className strings in the search bar.
 */
import React, { useState, useRef, useEffect } from "react";
import { optionsApi } from "@/api/client";
import type { OptionsChain, OptionQuote } from "@/types";
import {
  formatCurrency,
  formatIV,
  formatGreek,
  formatDate,
} from "@/utils/formatting";
import { Search, Loader2 } from "lucide-react";

export const OptionsChainPage: React.FC = () => {
  const [symbol, setSymbol]           = useState("");
  const [inputValue, setInputValue]   = useState("");
  const [expirations, setExpirations] = useState<string[]>([]);
  const [selectedExp, setSelectedExp] = useState<string>("");
  const [chain, setChain]             = useState<OptionsChain | null>(null);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState<string | null>(null);

  const loadSymbol = async () => {
    const sym = inputValue.toUpperCase().trim();
    if (!sym) return;
    setLoading(true);
    setError(null);
    try {
      const exps = await optionsApi.getExpirations(sym);
      setSymbol(sym);
      setExpirations(exps);
      if (exps.length > 0) {
        setSelectedExp(exps[0]);
        const c = await optionsApi.getChain(sym, exps[0]);
        setChain(c);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load options");
    } finally {
      setLoading(false);
    }
  };

  const loadExpiration = async (exp: string) => {
    if (!symbol) return;
    setSelectedExp(exp);
    setLoading(true);
    setError(null);
    try {
      const c = await optionsApi.getChain(symbol, exp);
      setChain(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load chain");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-0">

      {/* ── Search bar — fixed ────────────────────────────────────────── */}
      <div className="flex items-center gap-2 px-3 py-2.5 bg-gray-900 border-b border-gray-700 flex-shrink-0">
        <span className="hidden sm:block text-sm font-semibold text-white shrink-0">
          Options Chain
        </span>
        <div className="flex gap-2 flex-1 sm:ml-auto sm:flex-initial">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && loadSymbol()}
            placeholder="Symbol (e.g. AAPL)"
            className="flex-1 sm:w-44 bg-gray-800 border border-gray-600 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500"
          />
          <button
            onClick={loadSymbol}
            disabled={loading}
            className="flex items-center gap-1.5 px-3 py-2 bg-sky-600 hover:bg-sky-500 disabled:bg-gray-700 text-white text-sm rounded-lg font-medium transition-colors shrink-0"
          >
            <Search size={15} />
            <span className="hidden sm:inline">Load</span>
          </button>
        </div>
      </div>

      {/* ── Expiration pills — fixed ──────────────────────────────────── */}
      {expirations.length > 0 && (
        <div className="flex gap-1 overflow-x-auto px-3 py-2 bg-gray-900 border-b border-gray-700 flex-shrink-0">
          {expirations.slice(0, 16).map((exp) => (
            <button
              key={exp}
              onClick={() => loadExpiration(exp)}
              className={`px-2.5 py-1 text-xs font-medium rounded whitespace-nowrap transition-colors shrink-0 ${
                selectedExp === exp
                  ? "bg-sky-600 text-white"
                  : "bg-gray-700 text-gray-300 hover:bg-gray-600"
              }`}
            >
              {formatDate(exp)}
            </button>
          ))}
        </div>
      )}

      {/* ── Spot price bar — fixed (only when chain loaded) ───────────── */}
      {!loading && chain && (
        <div className="flex items-center gap-3 px-3 py-1.5 bg-gray-900/80 border-b border-gray-800 flex-shrink-0 text-xs text-gray-400">
          <span className="text-white font-bold text-sm">{chain.underlying}</span>
          <span>
            Spot:{" "}
            <span className="text-sky-300 font-mono">
              ${chain.spot_price.toFixed(2)}
            </span>
          </span>
          <span className="ml-auto text-gray-600">
            {chain.calls.length}C · {chain.puts.length}P
          </span>
        </div>
      )}

      {/* ── Scrollable body — fills remaining height ──────────────────── */}
      {/* overflow-auto here handles vertical scroll; table itself handles horizontal */}
      <div className="flex-1 min-h-0 overflow-auto pb-16 lg:pb-0">

        {loading && (
          <div className="h-full flex items-center justify-center">
            <Loader2 size={32} className="text-sky-500 animate-spin" />
          </div>
        )}

        {!loading && error && (
          <div className="mx-3 mt-3 text-red-400 text-sm bg-red-900/20 border border-red-700 rounded-lg p-3">
            {error}
          </div>
        )}

        {!loading && chain && <OptionsChainTable chain={chain} />}

        {!loading && !chain && !error && (
          <div className="h-full flex items-center justify-center text-gray-500 text-sm">
            Enter a symbol above to view its options chain
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Chain table with sticky strike column
// ---------------------------------------------------------------------------

const OptionsChainTable: React.FC<{ chain: OptionsChain }> = ({ chain }) => {
  const atmRowRef = useRef<HTMLTableRowElement | null>(null);

  // Merge calls and puts by strike
  const allStrikes = Array.from(
    new Set([
      ...chain.calls.map((c) => c.strike),
      ...chain.puts.map((p) => p.strike),
    ])
  ).sort((a, b) => a - b);

  const callsByStrike = Object.fromEntries(chain.calls.map((c) => [c.strike, c]));
  const putsByStrike  = Object.fromEntries(chain.puts.map((p) => [p.strike, p]));

  // Auto-scroll ATM row into view when chain changes
  useEffect(() => {
    if (atmRowRef.current) {
      atmRowRef.current.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [chain]);

  // Column class helpers
  const thCall = "px-2 py-1.5 text-right text-[10px] font-semibold text-green-500 uppercase tracking-wide whitespace-nowrap";
  const thPut  = "px-2 py-1.5 text-left  text-[10px] font-semibold text-red-400  uppercase tracking-wide whitespace-nowrap";
  const thStrike =
    "px-2 py-1.5 text-center text-[10px] font-semibold text-white uppercase tracking-wide whitespace-nowrap " +
    "sticky left-0 z-20 bg-gray-800 border-x border-gray-700 min-w-[64px]";

  const tdCall   = "px-2 py-1.5 text-right text-xs font-mono whitespace-nowrap";
  const tdPut    = "px-2 py-1.5 text-left  text-xs font-mono whitespace-nowrap";
  const tdStrike =
    "px-2 py-1.5 text-center text-xs font-bold whitespace-nowrap " +
    "sticky left-0 z-10 border-x border-gray-700";

  return (
    <table className="w-full border-collapse text-xs min-w-[480px]">
      <thead className="bg-gray-800 sticky top-0 z-20">
        <tr>
          {/* Call side headers */}
          <th className={thCall}>Bid</th>
          <th className={thCall}>Ask</th>
          <th className={`${thCall} hidden sm:table-cell`}>IV</th>
          <th className={`${thCall} hidden sm:table-cell`}>Δ</th>
          <th className={`${thCall} hidden md:table-cell`}>OI</th>
          {/* Strike — sticky */}
          <th className={thStrike}>Strike</th>
          {/* Put side headers */}
          <th className={`${thPut} hidden md:table-cell`}>OI</th>
          <th className={`${thPut} hidden sm:table-cell`}>Δ</th>
          <th className={`${thPut} hidden sm:table-cell`}>IV</th>
          <th className={thPut}>Bid</th>
          <th className={thPut}>Ask</th>
        </tr>
      </thead>
      <tbody>
        {allStrikes.map((strike) => {
          const call  = callsByStrike[strike];
          const put   = putsByStrike[strike];
          const isATM =
            chain.spot_price != null &&
            Math.abs(strike - chain.spot_price) / chain.spot_price < 0.02;

          return (
            <tr
              key={strike}
              ref={isATM ? atmRowRef : undefined}
              className={`border-b border-gray-800/60 ${
                isATM ? "bg-sky-900/20" : "hover:bg-gray-800/30"
              }`}
            >
              {/* Calls */}
              <td className={`${tdCall} text-green-400`}>
                {call?.bid != null ? formatCurrency(call.bid) : <Dash />}
              </td>
              <td className={`${tdCall} text-green-400`}>
                {call?.ask != null ? formatCurrency(call.ask) : <Dash />}
              </td>
              <td className={`${tdCall} text-gray-300 hidden sm:table-cell`}>
                {call?.implied_volatility != null ? formatIV(call.implied_volatility) : <Dash />}
              </td>
              <td className={`${tdCall} text-gray-300 hidden sm:table-cell`}>
                {call?.delta != null ? formatGreek(call.delta) : <Dash />}
              </td>
              <td className={`${tdCall} text-gray-400 hidden md:table-cell`}>
                {call?.open_interest != null ? call.open_interest.toLocaleString() : <Dash />}
              </td>

              {/* Strike — sticky */}
              <td
                className={`${tdStrike} ${
                  isATM
                    ? "text-sky-300 bg-sky-900/40"
                    : "text-white bg-gray-800"
                }`}
              >
                ${strike}
              </td>

              {/* Puts */}
              <td className={`${tdPut} text-gray-400 hidden md:table-cell`}>
                {put?.open_interest != null ? put.open_interest.toLocaleString() : <Dash />}
              </td>
              <td className={`${tdPut} text-gray-300 hidden sm:table-cell`}>
                {put?.delta != null ? formatGreek(put.delta) : <Dash />}
              </td>
              <td className={`${tdPut} text-gray-300 hidden sm:table-cell`}>
                {put?.implied_volatility != null ? formatIV(put.implied_volatility) : <Dash />}
              </td>
              <td className={`${tdPut} text-red-400`}>
                {put?.bid != null ? formatCurrency(put.bid) : <Dash />}
              </td>
              <td className={`${tdPut} text-red-400`}>
                {put?.ask != null ? formatCurrency(put.ask) : <Dash />}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
};

const Dash: React.FC = () => (
  <span className="text-gray-700">—</span>
);
