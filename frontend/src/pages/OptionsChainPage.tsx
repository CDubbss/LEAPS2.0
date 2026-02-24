import React, { useState } from "react";
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
  const [symbol, setSymbol] = useState("");
  const [inputValue, setInputValue] = useState("");
  const [expirations, setExpirations] = useState<string[]>([]);
  const [selectedExp, setSelectedExp] = useState<string>("");
  const [chain, setChain] = useState<OptionsChain | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    <div className="flex flex-col h-full overflow-hidden p-4 space-y-4">
      {/* Search */}
      <div className="flex gap-3 items-center">
        <h1 className="text-xl font-bold text-white">Options Chain</h1>
        <div className="flex gap-2 ml-auto">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && loadSymbol()}
            placeholder="Enter symbol (e.g. AAPL)"
            className="bg-gray-800 border border-gray-600 text-white text-sm rounded-lg px-3 py-2 w-48 focus:outline-none focus:border-sky-500"
          />
          <button
            onClick={loadSymbol}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded-lg font-medium"
          >
            <Search size={16} />
            Load
          </button>
        </div>
      </div>

      {/* Expiration tabs */}
      {expirations.length > 0 && (
        <div className="flex gap-1 overflow-x-auto pb-1">
          {expirations.slice(0, 12).map((exp) => (
            <button
              key={exp}
              onClick={() => loadExpiration(exp)}
              className={`px-3 py-1.5 text-xs font-medium rounded whitespace-nowrap transition-colors ${
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

      {/* Loading / Error */}
      {loading && (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 size={32} className="text-sky-500 animate-spin" />
        </div>
      )}
      {error && (
        <div className="text-red-400 text-sm bg-red-900/20 border border-red-700 rounded p-3">
          {error}
        </div>
      )}

      {/* Chain table */}
      {!loading && chain && (
        <div className="flex-1 overflow-auto">
          <div className="flex items-center gap-4 mb-3 text-sm text-gray-400">
            <span className="text-white font-bold text-lg">{chain.underlying}</span>
            <span>Spot: <span className="text-white">${chain.spot_price.toFixed(2)}</span></span>
            <span>{chain.calls.length} calls · {chain.puts.length} puts</span>
          </div>
          <OptionsChainTable chain={chain} />
        </div>
      )}

      {!loading && !chain && !error && (
        <div className="flex-1 flex items-center justify-center text-gray-500">
          Enter a symbol above to view its options chain
        </div>
      )}
    </div>
  );
};

const OptionsChainTable: React.FC<{ chain: OptionsChain }> = ({ chain }) => {
  // Merge calls and puts by strike
  const allStrikes = Array.from(
    new Set([
      ...chain.calls.map((c) => c.strike),
      ...chain.puts.map((p) => p.strike),
    ])
  ).sort((a, b) => a - b);

  const callsByStrike = Object.fromEntries(
    chain.calls.map((c) => [c.strike, c])
  );
  const putsByStrike = Object.fromEntries(chain.puts.map((p) => [p.strike, p]));

  const headerCls =
    "px-2 py-1.5 text-xs font-medium text-gray-400 uppercase tracking-wider";
  const cellCls = "px-2 py-1.5 text-xs font-mono";

  return (
    <table className="w-full border-collapse text-xs">
      <thead className="bg-gray-800 sticky top-0">
        <tr>
          {/* Calls */}
          <th className={`${headerCls} text-right text-green-500`}>Bid</th>
          <th className={`${headerCls} text-right text-green-500`}>Ask</th>
          <th className={`${headerCls} text-right text-green-500`}>IV</th>
          <th className={`${headerCls} text-right text-green-500`}>Delta</th>
          <th className={`${headerCls} text-right text-green-500`}>OI</th>
          {/* Strike */}
          <th className={`${headerCls} text-center bg-gray-700 text-white`}>
            Strike
          </th>
          {/* Puts */}
          <th className={`${headerCls} text-left text-red-400`}>OI</th>
          <th className={`${headerCls} text-left text-red-400`}>Delta</th>
          <th className={`${headerCls} text-left text-red-400`}>IV</th>
          <th className={`${headerCls} text-left text-red-400`}>Bid</th>
          <th className={`${headerCls} text-left text-red-400`}>Ask</th>
        </tr>
      </thead>
      <tbody>
        {allStrikes.map((strike) => {
          const call = callsByStrike[strike];
          const put = putsByStrike[strike];
          const isATM =
            Math.abs(strike - chain.spot_price) / chain.spot_price < 0.02;

          return (
            <tr
              key={strike}
              className={`border-b border-gray-800 ${
                isATM ? "bg-sky-900/20" : "hover:bg-gray-800/40"
              }`}
            >
              {/* Call columns */}
              <td className={`${cellCls} text-right text-green-400`}>
                {call ? formatCurrency(call.bid) : "-"}
              </td>
              <td className={`${cellCls} text-right text-green-400`}>
                {call ? formatCurrency(call.ask) : "-"}
              </td>
              <td className={`${cellCls} text-right text-gray-300`}>
                {call ? formatIV(call.implied_volatility) : "-"}
              </td>
              <td className={`${cellCls} text-right text-gray-300`}>
                {call ? formatGreek(call.delta) : "-"}
              </td>
              <td className={`${cellCls} text-right text-gray-400`}>
                {call ? call.open_interest.toLocaleString() : "-"}
              </td>
              {/* Strike */}
              <td
                className={`${cellCls} text-center font-bold bg-gray-700 ${
                  isATM ? "text-sky-300" : "text-white"
                }`}
              >
                ${strike}
              </td>
              {/* Put columns */}
              <td className={`${cellCls} text-left text-gray-400`}>
                {put ? put.open_interest.toLocaleString() : "-"}
              </td>
              <td className={`${cellCls} text-left text-gray-300`}>
                {put ? formatGreek(put.delta) : "-"}
              </td>
              <td className={`${cellCls} text-left text-gray-300`}>
                {put ? formatIV(put.implied_volatility) : "-"}
              </td>
              <td className={`${cellCls} text-left text-red-400`}>
                {put ? formatCurrency(put.bid) : "-"}
              </td>
              <td className={`${cellCls} text-left text-red-400`}>
                {put ? formatCurrency(put.ask) : "-"}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
};
