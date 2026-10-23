/**
 * TedPage — "The Ted" earnings IV-buildup gate checker (14 gates, v1.3).
 *
 * Strategy: buy a single call/put 7–14 days before earnings, expiry 1–2 days
 * past the print, exit BEFORE earnings. Profits from IV building into the
 * event — not the outcome. Any hard gate fail = no trade.
 *
 * Left: universe tickers with earnings inside the 7–14 day entry window.
 * Right: the gate checklist for one ticker — auto-computed where possible,
 * with the judgment calls (direction, contra-catalysts, sizing) left to you.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  positionsApi,
  tedApi,
  type TedCandidate,
  type TedCheckParams,
  type TedCheckResponse,
  type TedGate,
} from "@/api/client";
import { formatCurrency, formatDate } from "@/utils/formatting";
import { Briefcase, Check, Loader2, Play, Search, Zap } from "lucide-react";

const ACCOUNT_KEY = "leaps-ted-account";

const inputCls =
  "bg-gray-800 border border-gray-600 text-white text-xs rounded px-2 py-1.5 focus:outline-none focus:border-sky-500";

export const TedPage: React.FC = () => {
  const [candidates, setCandidates] = useState<TedCandidate[]>([]);
  const [candMessage, setCandMessage] = useState("");
  const [candLoading, setCandLoading] = useState(true);
  const [symbol, setSymbol] = useState("");
  const [searchInput, setSearchInput] = useState("");

  // Gate-check inputs
  const [direction, setDirection] = useState<"bull" | "bear">("bull");
  const [accountBalance, setAccountBalance] = useState<number>(() => {
    const saved = localStorage.getItem(ACCOUNT_KEY);
    return saved ? parseFloat(saved) : 10000;
  });
  const [contracts, setContracts] = useState(1);
  const [strike, setStrike] = useState<number | undefined>(undefined);
  const [bmoAmc, setBmoAmc] = useState<"bmo" | "amc">("amc");
  const [expectedIvGain, setExpectedIvGain] = useState(10);
  const [noContra, setNoContra] = useState(false);
  const [analystOverride, setAnalystOverride] = useState<boolean | undefined>(undefined);

  const [result, setResult] = useState<TedCheckResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tracked, setTracked] = useState(false);

  useEffect(() => {
    tedApi
      .getCandidates()
      .then((r) => {
        setCandidates(r.candidates);
        setCandMessage(r.message);
      })
      .catch((e) => setCandMessage(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setCandLoading(false));
  }, []);

  useEffect(() => {
    localStorage.setItem(ACCOUNT_KEY, String(accountBalance));
  }, [accountBalance]);

  const runCheck = useCallback(
    async (sym: string, overrides: Partial<TedCheckParams> = {}) => {
      if (!sym) return;
      setChecking(true);
      setError(null);
      setTracked(false);
      try {
        const params: TedCheckParams = {
          direction,
          account_balance: accountBalance,
          contracts,
          strike,
          bmo_amc: bmoAmc,
          expected_iv_gain: expectedIvGain,
          no_contra: noContra,
          analyst_override: analystOverride,
          ...overrides,
        };
        const r = await tedApi.check(sym, params);
        setResult(r);
        // Adopt the server's chosen strike so the selector reflects reality
        if (r.context.chosen_strike != null) setStrike(r.context.chosen_strike);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Check failed");
        setResult(null);
      } finally {
        setChecking(false);
      }
    },
    [direction, accountBalance, contracts, strike, bmoAmc, expectedIvGain, noContra, analystOverride]
  );

  const selectSymbol = (sym: string) => {
    setSymbol(sym);
    setStrike(undefined);
    setResult(null);
    void runCheck(sym, { strike: undefined });
  };

  const trackPosition = async () => {
    if (!result || !result.context.expiration || !strike) return;
    const chosen = result.context.strike_menu.find((s) => s.strike === strike);
    if (!chosen) return;
    await positionsApi.create({
      symbol: result.report.symbol,
      spread_type: result.report.option_type === "CALL" ? "ted_call" : "ted_put",
      long_strike: strike,
      long_option_type: result.context.option_side,
      short_strike: null,
      short_option_type: null,
      expiration: result.context.expiration,
      entry_date: new Date().toISOString().slice(0, 10),
      entry_debit: chosen.mid > 0 ? chosen.mid : chosen.ask,
      contracts: result.report.recommended_contracts,
      earnings_date: result.context.earnings_date,
      exit_by: result.report.exit_by,
      notes: `Ted ${result.report.verdict}: IV ${result.report.iv_score}/6, dir ${result.report.dir_score}/3`,
    });
    setTracked(true);
  };

  return (
    <div className="flex h-full min-h-0">
      {/* ── Candidates panel ─────────────────────────────────────────── */}
      <aside className="w-56 lg:w-64 bg-gray-900 border-r border-gray-700 flex flex-col flex-shrink-0 overflow-y-auto">
        <div className="p-3 border-b border-gray-700">
          <div className="flex items-center gap-1.5 text-white font-bold text-sm">
            <Zap size={15} className="text-amber-400" />
            The Ted
          </div>
          <p className="text-[10px] text-gray-500 mt-1 leading-snug">
            Earnings IV-buildup. Enter 7–14d before the print, exit before it.
            Any hard gate fail = no trade.
          </p>
        </div>

        {/* Ticker search */}
        <div className="p-2 border-b border-gray-800 flex gap-1.5">
          <input
            className={`${inputCls} flex-1 min-w-0`}
            placeholder="Any ticker…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && searchInput.trim()) {
                selectSymbol(searchInput.toUpperCase().trim());
              }
            }}
          />
          <button
            onClick={() => searchInput.trim() && selectSymbol(searchInput.toUpperCase().trim())}
            className="p-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-200"
            title="Run the gates on any ticker"
          >
            <Search size={13} />
          </button>
        </div>

        <div className="px-3 pt-2 text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
          Earnings in 7–14 days
        </div>
        <div className="flex-1 p-2 space-y-1">
          {candLoading && (
            <div className="flex justify-center py-6">
              <Loader2 size={18} className="text-sky-500 animate-spin" />
            </div>
          )}
          {!candLoading && candidates.length === 0 && (
            <p className="text-[11px] text-gray-600 px-1 leading-snug">
              {candMessage || "No universe tickers report earnings in the window."}
            </p>
          )}
          {candidates.map((c) => (
            <button
              key={c.symbol}
              onClick={() => selectSymbol(c.symbol)}
              className={`w-full flex items-center justify-between px-2 py-1.5 rounded text-xs transition-colors ${
                symbol === c.symbol
                  ? "bg-sky-900/50 text-white border border-sky-700"
                  : "text-gray-300 hover:bg-gray-800 border border-transparent"
              }`}
            >
              <span className="font-bold">{c.symbol}</span>
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] font-mono ${
                  c.ideal
                    ? "bg-green-900/50 text-green-300"
                    : "bg-amber-900/40 text-amber-300"
                }`}
                title={`Earnings ${c.earnings_date}${c.ideal ? " — ideal 10-12d window" : ""}`}
              >
                {c.days_out}d
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* ── Gate checklist panel ─────────────────────────────────────── */}
      <div className="flex-1 min-h-0 overflow-y-auto pb-16 lg:pb-4">
        {!symbol && (
          <div className="h-full flex items-center justify-center text-gray-500 text-sm">
            Pick a candidate or search a ticker to run the 14 gates
          </div>
        )}

        {symbol && (
          <div className="max-w-3xl mx-auto p-4 space-y-4">
            {/* Inputs */}
            <div className="bg-gray-800 rounded-lg p-3">
              <div className="flex items-baseline justify-between mb-2">
                <span className="text-lg font-bold text-white">
                  {symbol}
                  {result?.context.company_name && (
                    <span className="text-xs text-gray-500 font-normal ml-2">
                      {result.context.company_name}
                    </span>
                  )}
                </span>
                {result?.context.spot != null && (
                  <span className="text-sm font-mono text-sky-300">
                    ${result.context.spot.toFixed(2)}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                <label className="block">
                  <span className="text-[10px] text-gray-400">Thesis</span>
                  <div className="flex rounded overflow-hidden border border-gray-600">
                    {(["bull", "bear"] as const).map((d) => (
                      <button
                        key={d}
                        onClick={() => setDirection(d)}
                        className={`flex-1 py-1.5 text-xs font-medium ${
                          direction === d
                            ? d === "bull"
                              ? "bg-green-700 text-white"
                              : "bg-red-700 text-white"
                            : "bg-gray-800 text-gray-400"
                        }`}
                      >
                        {d === "bull" ? "BULL → CALL" : "BEAR → PUT"}
                      </button>
                    ))}
                  </div>
                </label>
                <label className="block">
                  <span className="text-[10px] text-gray-400">Account balance ($)</span>
                  <input
                    className={`${inputCls} w-full`}
                    type="number"
                    min={1}
                    value={accountBalance || ""}
                    onChange={(e) => setAccountBalance(parseFloat(e.target.value) || 0)}
                  />
                </label>
                <label className="block">
                  <span className="text-[10px] text-gray-400">Contracts</span>
                  <input
                    className={`${inputCls} w-full`}
                    type="number"
                    min={1}
                    value={contracts}
                    onChange={(e) => setContracts(parseInt(e.target.value) || 1)}
                  />
                </label>
                <label className="block">
                  <span className="text-[10px] text-gray-400">Report timing</span>
                  <select
                    className={`${inputCls} w-full`}
                    value={bmoAmc}
                    onChange={(e) => setBmoAmc(e.target.value as "bmo" | "amc")}
                  >
                    <option value="amc">AMC (after close)</option>
                    <option value="bmo">BMO (before open)</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-[10px] text-gray-400">Strike</span>
                  <select
                    className={`${inputCls} w-full`}
                    value={strike ?? ""}
                    onChange={(e) => setStrike(parseFloat(e.target.value))}
                    disabled={!result?.context.strike_menu.length}
                  >
                    {(result?.context.strike_menu ?? []).map((s) => (
                      <option key={s.strike} value={s.strike}>
                        {s.strike} — ${s.mid.toFixed(2)} (OI {s.open_interest})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-[10px] text-gray-400">Expected IV gain (pts)</span>
                  <input
                    className={`${inputCls} w-full`}
                    type="number"
                    min={1}
                    value={expectedIvGain}
                    onChange={(e) => setExpectedIvGain(parseFloat(e.target.value) || 10)}
                  />
                </label>
                <label className="flex items-end gap-1.5 text-xs text-gray-300 pb-1.5 col-span-2">
                  <input
                    type="checkbox"
                    checked={noContra}
                    onChange={(e) => setNoContra(e.target.checked)}
                    className="accent-sky-500"
                  />
                  <span>
                    No contra-catalysts before exit confirmed{" "}
                    <span className="text-gray-500">(Fed, launches, analyst days…)</span>
                  </span>
                </label>
              </div>
              <div className="flex items-center gap-2 mt-3">
                <button
                  onClick={() => void runCheck(symbol)}
                  disabled={checking || accountBalance <= 0}
                  className="flex items-center gap-1.5 px-4 py-2 bg-sky-600 hover:bg-sky-500 disabled:bg-gray-700 disabled:text-gray-500 text-white text-sm rounded-lg font-medium transition-colors"
                >
                  {checking ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Play size={14} />
                  )}
                  Run Gates
                </button>
                {result?.context.earnings_date && (
                  <span className="text-xs text-gray-400">
                    Earnings {formatDate(result.context.earnings_date)} · expiry{" "}
                    {result.context.expiration
                      ? formatDate(result.context.expiration)
                      : "none qualifying"}
                  </span>
                )}
              </div>
            </div>

            {error && (
              <div className="text-red-400 text-sm bg-red-900/20 border border-red-700 rounded-lg p-3">
                {error}
              </div>
            )}

            {checking && !result && (
              <div className="flex justify-center py-10">
                <Loader2 size={28} className="text-sky-500 animate-spin" />
              </div>
            )}

            {result && (
              <>
                <VerdictBanner
                  report={result.report}
                  onTrack={() => void trackPosition()}
                  tracked={tracked}
                  canTrack={!!result.context.expiration && !!strike}
                />

                <GateSection
                  title="I — Hard Gates (any fail = no trade)"
                  color="text-red-400"
                  gates={result.report.gates.filter((g) => [1, 2, 3, 4, 5].includes(g.num))}
                />
                <GateSection
                  title={`II — IV Buildup Gates (${result.report.iv_score}/6)`}
                  color="text-amber-400"
                  gates={result.report.gates.filter((g) => [6, 7, 8, 12, 13, 14].includes(g.num))}
                />
                <GateSection
                  title={`III — Direction Signals (${result.report.dir_score}/3)`}
                  color="text-sky-400"
                  gates={result.report.gates.filter((g) => [9, 10, 11].includes(g.num))}
                />

                {/* Gate 9 manual override when data unavailable */}
                {result.report.gates.some((g) => g.num === 9 && g.status === "manual") && (
                  <label className="flex items-center gap-1.5 text-xs text-gray-300 px-1">
                    <input
                      type="checkbox"
                      checked={analystOverride === true}
                      onChange={(e) =>
                        setAnalystOverride(e.target.checked ? true : undefined)
                      }
                      className="accent-sky-500"
                    />
                    Analyst consensus is majority Buy with meaningful upside (manual
                    confirmation — re-run gates after checking)
                  </label>
                )}

                {/* Sizing + exit timing */}
                <div className="grid sm:grid-cols-2 gap-3">
                  <div className="bg-gray-800 rounded-lg p-3">
                    <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-1">
                      Position
                    </div>
                    <div className="text-sm text-gray-200 space-y-1">
                      <div>
                        Cost:{" "}
                        <span className="font-mono text-white">
                          {result.report.total_cost != null
                            ? formatCurrency(result.report.total_cost)
                            : "—"}
                        </span>
                        {result.report.pct_of_account != null && (
                          <span className="text-gray-500">
                            {" "}
                            ({result.report.pct_of_account.toFixed(0)}% of account)
                          </span>
                        )}
                      </div>
                      <div>
                        Recommended contracts:{" "}
                        <span className="font-bold text-white">
                          {result.report.recommended_contracts}
                        </span>
                        {result.report.recommended_contracts !== contracts && (
                          <span className="text-gray-500"> (entered: {contracts})</span>
                        )}
                      </div>
                    </div>
                    {result.report.sizing_notes.length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {result.report.sizing_notes.map((n, i) => (
                          <li key={i} className="text-[11px] text-amber-300">
                            • {n}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div className="bg-gray-800 rounded-lg p-3">
                    <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-1">
                      Exit Timing
                    </div>
                    <p className="text-sm text-gray-200">{result.report.exit_window_text}</p>
                    <p className="text-[11px] text-gray-500 mt-2">
                      Intraday spike → take it early. Contra-catalyst hits → exit
                      immediately regardless of P&L.
                    </p>
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------

const VerdictBanner: React.FC<{
  report: TedCheckResponse["report"];
  onTrack: () => void;
  tracked: boolean;
  canTrack: boolean;
}> = ({ report, onTrack, tracked, canTrack }) => {
  const styles: Record<string, string> = {
    TRADE: "bg-green-900/40 border-green-600 text-green-300",
    CAUTION: "bg-amber-900/30 border-amber-600 text-amber-300",
    WEAK: "bg-red-900/25 border-red-800 text-red-300",
    NO_TRADE: "bg-red-900/40 border-red-600 text-red-300",
  };
  const labels: Record<string, string> = {
    TRADE: "TRADE",
    CAUTION: "PROCEED WITH CAUTION",
    WEAK: "WEAK SETUP — CONSIDER SKIPPING",
    NO_TRADE: "NO TRADE — HARD GATE FAIL",
  };
  return (
    <div className={`border rounded-lg p-3 ${styles[report.verdict]}`}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <div className="font-bold text-base">{labels[report.verdict]}</div>
          <div className="text-xs opacity-90 mt-0.5">{report.verdict_detail}</div>
        </div>
        {report.verdict !== "NO_TRADE" && (
          <button
            onClick={onTrack}
            disabled={tracked || !canTrack}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              tracked
                ? "bg-green-900/40 text-green-400"
                : "bg-sky-600 hover:bg-sky-500 text-white"
            }`}
            title="Track this trade on the Positions page with an exit-before-print deadline"
          >
            {tracked ? <Check size={13} /> : <Briefcase size={13} />}
            {tracked ? "Tracked" : "Track"}
          </button>
        )}
      </div>
    </div>
  );
};

const GateSection: React.FC<{
  title: string;
  color: string;
  gates: TedGate[];
}> = ({ title, color, gates }) => (
  <div className="bg-gray-800 rounded-lg p-3">
    <div className={`text-xs font-semibold uppercase tracking-wide mb-2 ${color}`}>
      {title}
    </div>
    <div className="space-y-1.5">
      {gates.map((g) => (
        <GateRow key={g.num} gate={g} />
      ))}
    </div>
  </div>
);

const GateRow: React.FC<{ gate: TedGate }> = ({ gate }) => {
  const icon =
    gate.status === "pass" ? (
      <span className="text-green-400 font-bold">✓</span>
    ) : gate.status === "fail" ? (
      <span className="text-red-400 font-bold">✗</span>
    ) : gate.status === "manual" ? (
      <span className="text-sky-400 font-bold">?</span>
    ) : (
      <span className="text-amber-400 font-bold">⚠</span>
    );
  return (
    <div className="flex gap-2 text-xs">
      <span className="w-4 text-center shrink-0">{icon}</span>
      <span className="text-gray-500 font-mono shrink-0">G{String(gate.num).padStart(2, "0")}</span>
      <div className="min-w-0">
        <span
          className={
            gate.status === "fail"
              ? "text-red-300"
              : gate.status === "pass"
                ? "text-gray-200"
                : "text-amber-200"
          }
        >
          {gate.name}
          {gate.hard && gate.status === "fail" && (
            <span className="ml-1.5 px-1 rounded bg-red-900/60 text-red-300 text-[9px] font-bold">
              HARD
            </span>
          )}
          {!gate.auto && (
            <span className="ml-1.5 text-[9px] text-gray-500">(manual)</span>
          )}
        </span>
        {gate.detail && (
          <div className="text-[11px] text-gray-500 leading-snug">{gate.detail}</div>
        )}
      </div>
    </div>
  );
};
