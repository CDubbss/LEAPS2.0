import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from "recharts";
import { mlApi, type TickerSpread, type BucketSpread, type SpreadDetail } from "@/api/client";
import { RefreshCw } from "lucide-react";

// ─── Types ───────────────────────────────────────────────────────────────────

type MLStatus = { is_trained: boolean; mode: string; message: string };

type MLDbStats = {
  total: number;
  labeled: number;
  unlabeled: number;
  snapshots: number;
  training_threshold: number;
  ready_to_train: boolean;
  recent_scans: Array<{ date: string; scans: number; candidates: number }>;
  best_sell_days_distribution: Array<{ best_sell_days: number; count: number }>;
  score_distribution: Array<{ bucket: number; count: number }>;
  snapshot_intervals: Array<{ days_since_entry: number; count: number }>;
  avg_sell_days_by_type: Array<{ spread_type: string; avg_days: number; count: number }>;
  tickers_with_snapshots: string[];
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SPREAD_TYPE_LABELS: Record<string, string> = {
  bull_call: "Bull Call",
  bear_put: "Bear Put",
  leap_call: "LEAPS Call",
  leap_put: "LEAPS Put",
  leaps_spread_call: "LEAPS Spread",
};

const TOOLTIP_STYLE = {
  backgroundColor: "#1f2937",
  border: "1px solid #374151",
  borderRadius: "6px",
  color: "#f9fafb",
  fontSize: "12px",
};

const SNAPSHOT_DAYS = [7, 14, 21, 30, 45, 60, 90];

const LINE_COLORS = [
  "#0ea5e9", "#22c55e", "#f59e0b", "#818cf8",
  "#f43f5e", "#06b6d4", "#84cc16", "#e879f9",
];

// ─── Ticker Snapshot Chart ────────────────────────────────────────────────────

function TickerSnapshotChart({ tickers }: { tickers: string[] }) {
  const [selected, setSelected] = useState<string>(tickers[0] ?? "");
  const [spreads, setSpreads] = useState<TickerSpread[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    mlApi
      .getTickerSnapshotHistory(selected)
      .then((r) => setSpreads(r.spreads))
      .catch(() => setSpreads([]))
      .finally(() => setLoading(false));
  }, [selected]);

  if (tickers.length === 0) return null;

  // Build chart data: one point per snapshot day, one key per spread entry
  const lineKeys = spreads.map(
    (s) =>
      `${s.entry_date} · ${SPREAD_TYPE_LABELS[s.spread_type] ?? s.spread_type}`
  );

  const chartData = SNAPSHOT_DAYS.map((day) => {
    const point: Record<string, number | string> = { day: `Day ${day}` };
    spreads.forEach((s, i) => {
      const snap = s.snapshots.find((sn) => sn.days_since_entry === day);
      if (snap?.pnl_pct != null) point[lineKeys[i]] = snap.pnl_pct;
    });
    return point;
  });

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-sm font-semibold text-gray-200">
          Spread P&amp;L by Snapshot Interval
        </h2>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="text-xs bg-gray-700 text-gray-200 border border-gray-600 rounded px-2 py-1 focus:outline-none focus:border-sky-500"
        >
          {tickers.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>
      <p className="text-xs text-gray-500 mb-4">
        P&amp;L % at each tracking interval for all logged {selected} spreads.
        Each line = one spread entry.
      </p>

      {loading ? (
        <div className="h-48 flex items-center justify-center text-gray-500 text-sm">
          <RefreshCw size={14} className="animate-spin mr-2" />
          Loading…
        </div>
      ) : spreads.length === 0 ? (
        <div className="h-48 flex items-center justify-center text-gray-600 text-sm">
          No snapshot data for {selected}.
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 4, left: 0 }}>
            <XAxis
              dataKey="day"
              tick={{ fill: "#9ca3af", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "#6b7280", fontSize: 10 }}
              axisLine={false}
              tickLine={false}
              width={38}
              tickFormatter={(v) => `${v > 0 ? "+" : ""}${v}%`}
            />
            <ReferenceLine y={0} stroke="#374151" strokeDasharray="3 3" />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(v: number, name: string) => [
                `${v > 0 ? "+" : ""}${v.toFixed(1)}%`,
                name,
              ]}
            />
            <Legend
              wrapperStyle={{ fontSize: "10px", color: "#9ca3af", paddingTop: "8px" }}
            />
            {lineKeys.map((key, i) => (
              <Line
                key={key}
                type="monotone"
                dataKey={key}
                stroke={LINE_COLORS[i % LINE_COLORS.length]}
                strokeWidth={1.5}
                dot={{ r: 3, strokeWidth: 0 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

// ─── Spread Detail Modal ─────────────────────────────────────────────────────

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  if (value === null || value === undefined) return null;
  return (
    <div className="flex justify-between items-baseline py-1 border-b border-gray-700/40">
      <span className="text-gray-400 text-xs">{label}</span>
      <span className="text-gray-100 text-xs font-medium ml-4 text-right">{value}</span>
    </div>
  );
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-widest text-gray-500 mb-2 mt-4">
        {title}
      </div>
      {children}
    </div>
  );
}

function pct(v: number | null, digits = 1) {
  if (v === null || v === undefined) return null;
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}
function raw(v: number | null, digits = 2, prefix = "") {
  if (v === null || v === undefined) return null;
  return `${prefix}${v.toFixed(digits)}`;
}

function SpreadDetailModal({
  detail,
  loading,
  onClose,
}: {
  detail: SpreadDetail | null;
  loading: boolean;
  onClose: () => void;
}) {
  if (!loading && !detail) return null;

  const pnlColor =
    (detail?.peak_pnl_pct ?? 0) >= 0 ? "text-green-400" : "text-red-400";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-2xl mx-4 max-h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-700 flex-shrink-0">
          {loading ? (
            <div className="flex items-center gap-2 text-gray-400 text-sm">
              <RefreshCw size={14} className="animate-spin" /> Loading…
            </div>
          ) : detail ? (
            <div>
              <div className="flex items-center gap-3">
                <span className="text-lg font-bold text-white">{detail.symbol}</span>
                <span className="text-xs bg-gray-700 text-gray-300 px-2 py-0.5 rounded">
                  {SPREAD_TYPE_LABELS[detail.spread_type] ?? detail.spread_type}
                </span>
                {detail.label_source && (
                  <span className="text-xs bg-sky-900/60 text-sky-300 px-2 py-0.5 rounded">
                    {LABEL_SOURCE_BADGE[detail.label_source] ?? detail.label_source}
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500 mt-1">
                Entered {detail.entry_date} · Expires {detail.expiration}
                {detail.best_sell_days != null && ` · Peak at Day ${detail.best_sell_days}`}
              </p>
            </div>
          ) : null}
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-200 text-lg leading-none ml-4 flex-shrink-0"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        {detail && !loading && (
          <div className="overflow-y-auto px-5 pb-5">

            {/* P&L summary strip */}
            <div className="grid grid-cols-3 gap-3 mt-4">
              {[
                { label: "Outcome Score", value: detail.outcome_score?.toFixed(1) ?? "—", color: "text-sky-300" },
                {
                  label: "Peak P&L %",
                  value: detail.peak_pnl_pct != null
                    ? `${detail.peak_pnl_pct >= 0 ? "+" : ""}${detail.peak_pnl_pct.toFixed(1)}%`
                    : "—",
                  color: pnlColor,
                },
                {
                  label: "Peak P&L $",
                  value: detail.peak_pnl_dollars != null
                    ? `${detail.peak_pnl_dollars >= 0 ? "+$" : "-$"}${Math.abs(detail.peak_pnl_dollars).toFixed(0)}`
                    : "—",
                  color: pnlColor,
                },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-gray-800 rounded-lg p-3 text-center">
                  <div className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</div>
                  <div className={`text-xl font-bold mt-1 ${color}`}>{value}</div>
                </div>
              ))}
            </div>

            <DetailSection title="Trade P&amp;L">
              {/* Spread width context */}
              {detail.spread_width != null && (
                <DetailRow
                  label="Spread width"
                  value={
                    <span>
                      ${detail.spread_width.toFixed(2)}{" "}
                      <span className="text-gray-500">/ share</span>
                      <span className="text-gray-400 ml-2">(${(detail.spread_width * 100).toFixed(0)} max value / contract)</span>
                    </span>
                  }
                />
              )}

              {/* Entry cost */}
              <DetailRow
                label="Paid at entry"
                value={
                  detail.entry_net_debit != null ? (() => {
                    const perContract = detail.entry_net_debit * 100;
                    const pctOfWidth = detail.spread_width
                      ? ((detail.entry_net_debit / detail.spread_width) * 100).toFixed(0)
                      : null;
                    return (
                      <span>
                        <span className="text-white font-semibold">${perContract.toFixed(0)}</span>
                        <span className="text-gray-500 ml-1">/ contract</span>
                        <span className="text-gray-500 ml-2">(${detail.entry_net_debit.toFixed(2)}/share{pctOfWidth ? ` · ${pctOfWidth}% of width` : ""})</span>
                      </span>
                    );
                  })() : null
                }
              />

              {/* Best-day credit */}
              <DetailRow
                label={`Credit if sold — best day (Day ${detail.best_sell_days ?? "?"}${detail.best_day_date ? ` · ${detail.best_day_date}` : ""})`}
                value={(() => {
                  if (detail.best_day_date && detail.best_day_date >= (detail.today_date ?? "")) {
                    return <span className="text-gray-500 italic">not yet reached</span>;
                  }
                  if (detail.credit_at_best_day == null || detail.entry_net_debit == null) {
                    return <span className="text-gray-500 italic">unavailable — bad option data at snapshot</span>;
                  }
                  const creditContract = detail.credit_at_best_day * 100;
                  const netContract = (detail.credit_at_best_day - detail.entry_net_debit) * 100;
                  const isWin = netContract >= 0;
                  return (
                    <span>
                      <span className="text-white font-semibold">${creditContract.toFixed(0)}</span>
                      <span className="text-gray-500 ml-1">/ contract</span>
                      <span className="text-gray-500 ml-2">(${detail.credit_at_best_day.toFixed(2)}/share)</span>
                      <span className={`ml-2 font-medium ${isWin ? "text-green-400" : "text-red-400"}`}>
                        {netContract >= 0 ? "+$" : "-$"}{Math.abs(netContract).toFixed(0)} net
                      </span>
                    </span>
                  );
                })()}
              />

              {/* Today credit */}
              <DetailRow
                label={`Credit if sold today (${detail.today_date ?? "latest"}) · live est.`}
                value={(() => {
                  if (detail.credit_today == null || detail.entry_net_debit == null) {
                    return <span className="text-gray-500 italic">unavailable — market closed or data issue</span>;
                  }
                  const creditContract = detail.credit_today * 100;
                  const netContract = (detail.credit_today - detail.entry_net_debit) * 100;
                  const isWin = netContract >= 0;
                  return (
                    <span>
                      <span className="text-white font-semibold">${creditContract.toFixed(0)}</span>
                      <span className="text-gray-500 ml-1">/ contract</span>
                      <span className="text-gray-500 ml-2">(${detail.credit_today.toFixed(2)}/share)</span>
                      <span className={`ml-2 font-medium ${isWin ? "text-green-400" : "text-red-400"}`}>
                        {netContract >= 0 ? "+$" : "-$"}{Math.abs(netContract).toFixed(0)} net
                      </span>
                    </span>
                  );
                })()}
              />
            </DetailSection>

            <DetailSection title="Contract Legs">
              <DetailRow
                label="Long leg"
                value={
                  detail.long_strike != null
                    ? `$${detail.long_strike} ${(detail.long_option_type ?? "").toUpperCase()}`
                    : null
                }
              />
              <DetailRow
                label="Long mid at entry"
                value={detail.long_mid_at_entry != null ? `$${detail.long_mid_at_entry.toFixed(2)}` : null}
              />
              {detail.short_strike != null && (
                <>
                  <DetailRow
                    label="Short leg"
                    value={`$${detail.short_strike} ${(detail.short_option_type ?? "").toUpperCase()}`}
                  />
                  <DetailRow
                    label="Short mid at entry"
                    value={detail.short_mid_at_entry != null ? `$${detail.short_mid_at_entry.toFixed(2)}` : null}
                  />
                </>
              )}
              <DetailRow
                label="Net debit"
                value={detail.entry_net_debit != null ? `$${detail.entry_net_debit.toFixed(2)} / share ($${(detail.entry_net_debit * 100).toFixed(0)} / contract)` : null}
              />
              <DetailRow
                label="Spot at entry"
                value={detail.spot_at_entry != null ? `$${detail.spot_at_entry.toFixed(2)}` : null}
              />
              <DetailRow
                label={`Spot on best day (Day ${detail.best_sell_days ?? "?"}${detail.best_day_date ? ` · ${detail.best_day_date}` : ""})`}
                value={
                  detail.best_day_date && detail.best_day_date >= (detail.today_date ?? "") ? (
                    <span className="text-gray-500 italic">not yet reached ({detail.best_day_date})</span>
                  ) : detail.spot_at_best_day != null ? (
                    <span>
                      ${detail.spot_at_best_day.toFixed(2)}
                      {detail.spot_at_entry != null && (
                        <span className={
                          detail.spot_at_best_day >= detail.spot_at_entry
                            ? "text-green-400 ml-2"
                            : "text-red-400 ml-2"
                        }>
                          ({detail.spot_at_best_day >= detail.spot_at_entry ? "+" : ""}
                          {(((detail.spot_at_best_day - detail.spot_at_entry) / detail.spot_at_entry) * 100).toFixed(1)}%)
                        </span>
                      )}
                    </span>
                  ) : <span className="text-gray-500 italic">unavailable</span>
                }
              />
              <DetailRow
                label={`Spot today (${detail.today_date ?? "latest close"})`}
                value={
                  detail.spot_today != null ? (
                    <span>
                      ${detail.spot_today.toFixed(2)}
                      {detail.spot_at_entry != null && (
                        <span className={
                          detail.spot_today >= detail.spot_at_entry
                            ? "text-green-400 ml-2"
                            : "text-red-400 ml-2"
                        }>
                          ({detail.spot_today >= detail.spot_at_entry ? "+" : ""}
                          {(((detail.spot_today - detail.spot_at_entry) / detail.spot_at_entry) * 100).toFixed(1)}%)
                        </span>
                      )}
                    </span>
                  ) : null
                }
              />
              <DetailRow
                label="DTE at entry"
                value={detail.dte != null ? `${detail.dte} days` : null}
              />
            </DetailSection>

            <DetailSection title="Greeks at Entry">
              <DetailRow label="Delta"   value={raw(detail.delta, 3)} />
              <DetailRow label="Gamma"   value={raw(detail.gamma, 4)} />
              <DetailRow label="Theta"   value={detail.theta != null ? `${detail.theta.toFixed(4)} / day` : null} />
              <DetailRow label="IV Rank" value={detail.iv_rank != null ? `${detail.iv_rank.toFixed(1)}` : null} />
              <DetailRow label="IV Percentile" value={detail.iv_pct != null ? `${detail.iv_pct.toFixed(1)}` : null} />
              <DetailRow label="IV / HV ratio" value={raw(detail.iv_vs_hv, 2)} />
              <DetailRow label="Bid-ask spread" value={detail.bid_ask_pct != null ? `${(detail.bid_ask_pct * 100).toFixed(1)}%` : null} />
            </DetailSection>

            <DetailSection title="Spread Structure">
              <DetailRow label="Moneyness" value={detail.moneyness != null ? `${(detail.moneyness * 100).toFixed(1)}%` : null} />
              <DetailRow label="Spread width" value={detail.spread_width_pct != null ? `${(detail.spread_width_pct * 100).toFixed(1)}% of spot` : null} />
              <DetailRow label="Max risk/reward" value={raw(detail.max_risk_reward, 2)} />
              <DetailRow label="Debit % of width" value={detail.net_debit_pct_of_spread != null ? `${(detail.net_debit_pct_of_spread * 100).toFixed(1)}%` : null} />
            </DetailSection>

            <DetailSection title="Fundamentals at Entry">
              <DetailRow label="Fundamental score" value={detail.fundamental_score != null ? `${detail.fundamental_score.toFixed(1)} / 100` : null} />
              <DetailRow label="P/E ratio"         value={raw(detail.pe_ratio, 1)} />
              <DetailRow label="Revenue growth"    value={pct(detail.revenue_growth)} />
              <DetailRow label="Debt / equity"     value={raw(detail.debt_to_equity, 2)} />
              <DetailRow label="Gross margin"      value={pct(detail.gross_margin)} />
            </DetailSection>

            <DetailSection title="Sentiment at Entry">
              <DetailRow label="Sentiment score"    value={detail.sentiment_score != null ? `${detail.sentiment_score.toFixed(1)} / 100` : null} />
              <DetailRow label="Compound (pos−neg)" value={raw(detail.sentiment_compound, 3)} />
            </DetailSection>

            <DetailSection title="Price Context at Entry">
              <DetailRow label="vs 52-week high" value={pct(detail.price_vs_52w_high)} />
              <DetailRow label="vs 52-week low"  value={pct(detail.price_vs_52w_low)} />
            </DetailSection>

          </div>
        )}
      </div>
    </div>
  );
}

// ─── Score Bucket Drill-Down ─────────────────────────────────────────────────

const LABEL_SOURCE_BADGE: Record<string, string> = {
  interim_10d:  "10d",
  interim_21d:  "21d",
  interim_30d:  "30d",
  interim_90d:  "90d",
  interim_180d: "180d",
  interim_360d: "360d",
  expiry:       "Expiry",
};

function BucketDrillDown({
  bucket,
  spreads,
  loading,
  onClose,
  onRowClick,
}: {
  bucket: number;
  spreads: BucketSpread[];
  loading: boolean;
  onClose: () => void;
  onRowClick: (id: number) => void;
}) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-sky-700/50">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-200">
            Score bucket&nbsp;
            <span className="text-sky-300">{bucket}–{bucket + 10}</span>
          </h3>
          {!loading && (
            <p className="text-xs text-gray-500 mt-0.5">{spreads.length} spread{spreads.length !== 1 ? "s" : ""}</p>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1 rounded hover:bg-gray-700 transition-colors"
        >
          ✕ close
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-gray-500 text-xs py-4">
          <RefreshCw size={12} className="animate-spin" /> Loading…
        </div>
      ) : spreads.length === 0 ? (
        <p className="text-xs text-gray-500 py-4">No spreads in this bucket.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-700">
                <th className="text-left py-1.5 font-medium">Symbol</th>
                <th className="text-left py-1.5 font-medium">Type</th>
                <th className="text-left py-1.5 font-medium">Entry</th>
                <th className="text-left py-1.5 font-medium">Expiry</th>
                <th className="text-right py-1.5 font-medium">Score</th>
                <th className="text-right py-1.5 font-medium">Peak P&amp;L %</th>
                <th className="text-right py-1.5 font-medium">Peak P&amp;L $</th>
                <th className="text-right py-1.5 font-medium">Best Day</th>
                <th className="text-right py-1.5 font-medium">Label</th>
              </tr>
            </thead>
            <tbody>
              {spreads.map((s, i) => {
                const pnlPos = (s.peak_pnl_pct ?? 0) >= 0;
                const pnlColor = pnlPos ? "text-green-400" : "text-red-400";
                return (
                  <tr
                    key={i}
                    className="border-b border-gray-700/40 hover:bg-gray-700/40 cursor-pointer"
                    onClick={() => onRowClick(s.id)}
                    title="Click to see full spread details"
                  >
                    <td className="py-1.5 font-mono font-bold text-white">{s.symbol}</td>
                    <td className="py-1.5 text-gray-400">
                      {SPREAD_TYPE_LABELS[s.spread_type] ?? s.spread_type}
                    </td>
                    <td className="py-1.5 text-gray-400 font-mono">{s.entry_date}</td>
                    <td className="py-1.5 text-gray-400 font-mono">{s.expiration}</td>
                    <td className="py-1.5 text-right text-sky-300 font-medium">
                      {s.outcome_score.toFixed(1)}
                    </td>
                    <td className={`py-1.5 text-right font-medium ${pnlColor}`}>
                      {s.peak_pnl_pct != null
                        ? `${s.peak_pnl_pct >= 0 ? "+" : ""}${s.peak_pnl_pct.toFixed(1)}%`
                        : "—"}
                    </td>
                    <td className={`py-1.5 text-right font-medium ${pnlColor}`}>
                      {s.peak_pnl_dollars != null
                        ? `${s.peak_pnl_dollars >= 0 ? "+$" : "-$"}${Math.abs(s.peak_pnl_dollars).toFixed(0)}`
                        : "—"}
                    </td>
                    <td className="py-1.5 text-right text-gray-400">
                      {s.best_sell_days != null ? `Day ${s.best_sell_days}` : "—"}
                    </td>
                    <td className="py-1.5 text-right">
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-gray-700 text-gray-400">
                        {s.label_source ? (LABEL_SOURCE_BADGE[s.label_source] ?? s.label_source) : "—"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: number | string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 flex flex-col gap-1">
      <div className="text-xs text-gray-400 uppercase tracking-wide">{label}</div>
      <div className={`text-3xl font-bold ${accent ?? "text-white"}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500">{sub}</div>}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function MLDashboardPage() {
  const [status, setStatus] = useState<MLStatus | null>(null);
  const [stats, setStats] = useState<MLDbStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  // Score bucket drill-down
  const [selectedBucket, setSelectedBucket] = useState<number | null>(null);
  const [bucketSpreads, setBucketSpreads] = useState<BucketSpread[]>([]);
  const [bucketLoading, setBucketLoading] = useState(false);

  // Spread detail modal
  const [detailSpread, setDetailSpread] = useState<SpreadDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const openDetail = (id: number) => {
    setDetailLoading(true);
    setDetailSpread(null);
    mlApi.getSpreadDetail(id)
      .then(setDetailSpread)
      .catch(() => setDetailSpread(null))
      .finally(() => setDetailLoading(false));
  };

  const handleBucketClick = (data: { bucket: number }) => {
    const b = data.bucket;
    if (selectedBucket === b) {
      setSelectedBucket(null);
      return;
    }
    setSelectedBucket(b);
    setBucketLoading(true);
    mlApi.getScoreBucket(b)
      .then(setBucketSpreads)
      .catch(() => setBucketSpreads([]))
      .finally(() => setBucketLoading(false));
  };

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, d] = await Promise.all([mlApi.getStatus(), mlApi.getDbStats()]);
      setStatus(s);
      setStats(d);
      setLastRefresh(new Date());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load ML data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        <RefreshCw size={20} className="animate-spin mr-2" />
        Loading ML data…
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        {error}
      </div>
    );
  }

  const threshold = stats?.training_threshold ?? 500;
  const labeled = stats?.labeled ?? 0;
  const progressPct = Math.min(100, Math.round((labeled / threshold) * 100));

  // Fill score distribution buckets 0-90 (even if no data)
  const scoreBuckets = Array.from({ length: 10 }, (_, i) => {
    const bucket = i * 10;
    const found = stats?.score_distribution.find((r) => r.bucket === bucket);
    return { label: `${bucket}–${bucket + 10}`, bucket, count: found?.count ?? 0 };
  });

  return (
    <div className="h-full overflow-y-auto bg-gray-950 p-6">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-white">ML Training Dashboard</h1>
            <p className="text-xs text-gray-500 mt-0.5">
              Last refreshed {lastRefresh.toLocaleTimeString()}
            </p>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-md transition-colors"
          >
            <RefreshCw size={13} />
            Refresh
          </button>
        </div>

        {/* Status Banner */}
        {status && (
          <div
            className={`rounded-lg px-4 py-3 flex items-center gap-3 ${
              status.is_trained
                ? "bg-green-900/40 border border-green-700"
                : "bg-amber-900/40 border border-amber-700"
            }`}
          >
            <span
              className={`inline-block w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                status.is_trained ? "bg-green-400" : "bg-amber-400"
              }`}
            />
            <div>
              <span
                className={`font-semibold text-sm ${
                  status.is_trained ? "text-green-300" : "text-amber-300"
                }`}
              >
                Model: {status.is_trained ? "Trained & Active" : "Placeholder Mode"}
              </span>
              <p className="text-xs text-gray-400 mt-0.5">{status.message}</p>
            </div>
          </div>
        )}

        {/* Stat Cards */}
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard
              label="Total Logged"
              value={stats.total.toLocaleString()}
              sub="spread candidates"
              accent="text-sky-300"
            />
            <StatCard
              label="Labeled"
              value={stats.labeled.toLocaleString()}
              sub="outcome scores set"
              accent="text-green-300"
            />
            <StatCard
              label="Unlabeled"
              value={stats.unlabeled.toLocaleString()}
              sub="awaiting snapshots"
              accent="text-amber-300"
            />
            <StatCard
              label="Price Snapshots"
              value={stats.snapshots.toLocaleString()}
              sub="interval checks stored"
            />
          </div>
        )}

        {/* Progress to Training */}
        {stats && (
          <div className="bg-gray-800 rounded-lg p-4 space-y-2">
            <div className="flex justify-between items-baseline">
              <span className="text-sm text-gray-300 font-medium">
                Progress to Training
              </span>
              <span className="text-xs text-gray-400">
                {labeled.toLocaleString()} / {threshold.toLocaleString()} labeled samples
              </span>
            </div>
            <div className="h-3 bg-gray-700 rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  stats.ready_to_train ? "bg-green-500" : "bg-sky-500"
                }`}
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-gray-500">
              <span>{progressPct}% complete</span>
              {stats.ready_to_train ? (
                <span className="text-green-400 font-medium">
                  Ready — run: python -m backend.ml.train
                </span>
              ) : (
                <span>{threshold - labeled} more needed</span>
              )}
            </div>
          </div>
        )}

        {/* Outcome Score Distribution */}
        <div className="bg-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-200 mb-1">
            Outcome Score Distribution
          </h2>
          <p className="text-xs text-gray-500 mb-4">
            0 = total loss, 50 = break-even, 100 = doubled.{" "}
            {labeled > 0 && (
              <span className="text-gray-600">Click a bar to see individual spreads.</span>
            )}
          </p>
          {labeled === 0 ? (
            <div className="h-40 flex items-center justify-center text-gray-600 text-sm">
              No labeled data yet — labeling runs automatically at 9 AM daily via Task Scheduler.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart
                data={scoreBuckets}
                margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
                onClick={(data) => {
                  if (data?.activePayload?.[0]?.payload) {
                    handleBucketClick(data.activePayload[0].payload);
                  }
                }}
                style={{ cursor: "pointer" }}
              >
                <XAxis
                  dataKey="label"
                  tick={{ fill: "#9ca3af", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: "#6b7280", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  width={28}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [v, "Spreads"]}
                  cursor={{ fill: "rgba(255,255,255,0.05)" }}
                />
                <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                  {scoreBuckets.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={
                        entry.bucket === selectedBucket
                          ? "#ffffff"         // white — selected
                          : i >= 6
                          ? "#22c55e"         // green — high quality
                          : i >= 4
                          ? "#0ea5e9"         // sky — mid
                          : "#f59e0b"         // amber — low quality
                      }
                      opacity={selectedBucket !== null && entry.bucket !== selectedBucket ? 0.4 : 1}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Bucket Drill-Down */}
        {selectedBucket !== null && (
          <BucketDrillDown
            bucket={selectedBucket}
            spreads={bucketSpreads}
            loading={bucketLoading}
            onClose={() => setSelectedBucket(null)}
            onRowClick={openDetail}
          />
        )}

        {/* Spread Detail Modal */}
        {(detailLoading || detailSpread) && (
          <SpreadDetailModal
            detail={detailSpread}
            loading={detailLoading}
            onClose={() => { setDetailSpread(null); setDetailLoading(false); }}
          />
        )}

        {/* Best Sell Days Distribution */}
        <div className="bg-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-200 mb-1">
            Best Sell Days Distribution
          </h2>
          <p className="text-xs text-gray-500 mb-4">
            Day after entry when peak P&amp;L occurred across all labeled spreads.
          </p>
          {(stats?.best_sell_days_distribution.length ?? 0) === 0 ? (
            <div className="h-40 flex items-center justify-center text-gray-600 text-sm">
              No labeled data yet.
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <BarChart
                data={stats!.best_sell_days_distribution}
                margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
              >
                <XAxis
                  dataKey="best_sell_days"
                  tick={{ fill: "#9ca3af", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  tickFormatter={(v) => `Day ${v}`}
                />
                <YAxis
                  tick={{ fill: "#6b7280", fontSize: 10 }}
                  axisLine={false}
                  tickLine={false}
                  width={28}
                />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v: number) => [v, "Spreads"]}
                  labelFormatter={(l) => `Day ${l}`}
                />
                <Bar dataKey="count" fill="#818cf8" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Snapshot Coverage */}
        {(stats?.snapshot_intervals.length ?? 0) > 0 && (
          <div className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-200 mb-3">
              Price Snapshot Coverage
            </h2>
            <div className="flex flex-wrap gap-2">
              {[7, 14, 21, 30, 45, 60, 90].map((day) => {
                const found = stats!.snapshot_intervals.find(
                  (r) => r.days_since_entry === day
                );
                return (
                  <div
                    key={day}
                    className={`flex flex-col items-center px-3 py-2 rounded text-xs ${
                      found ? "bg-sky-900/50 text-sky-300" : "bg-gray-700 text-gray-600"
                    }`}
                  >
                    <span className="font-bold">{found?.count ?? 0}</span>
                    <span>Day {day}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Ticker Snapshot Chart */}
        {(stats?.tickers_with_snapshots?.length ?? 0) > 0 && (
          <TickerSnapshotChart tickers={stats!.tickers_with_snapshots} />
        )}

        {/* Recent Scan Activity */}
        <div className="bg-gray-800 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-200 mb-3">
            Recent Scan Activity
            <span className="text-gray-500 font-normal ml-1">(last 14 days)</span>
          </h2>
          {(stats?.recent_scans.length ?? 0) === 0 ? (
            <p className="text-sm text-gray-500">No scans recorded yet. Run a scan to start collecting data.</p>
          ) : (
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left py-1.5 font-medium">Date</th>
                  <th className="text-right py-1.5 font-medium">Scans</th>
                  <th className="text-right py-1.5 font-medium">Candidates Logged</th>
                </tr>
              </thead>
              <tbody>
                {stats!.recent_scans.map((row) => (
                  <tr key={row.date} className="border-b border-gray-700/50">
                    <td className="py-1.5 text-gray-300 font-mono">{row.date}</td>
                    <td className="py-1.5 text-right text-gray-300">{row.scans}</td>
                    <td className="py-1.5 text-right text-sky-300 font-medium">{row.candidates}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Best Sell Days by Spread Type */}
        {(stats?.avg_sell_days_by_type.length ?? 0) > 0 && (
          <div className="bg-gray-800 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-200 mb-3">
              Avg Best Sell Day by Spread Type
            </h2>
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left py-1.5 font-medium">Spread Type</th>
                  <th className="text-right py-1.5 font-medium">Avg Best Day</th>
                  <th className="text-right py-1.5 font-medium">Sample Size</th>
                </tr>
              </thead>
              <tbody>
                {stats!.avg_sell_days_by_type.map((row) => (
                  <tr key={row.spread_type} className="border-b border-gray-700/50">
                    <td className="py-1.5 text-gray-300">
                      {SPREAD_TYPE_LABELS[row.spread_type] ?? row.spread_type}
                    </td>
                    <td className="py-1.5 text-right text-indigo-300 font-medium">
                      Day {row.avg_days}
                    </td>
                    <td className="py-1.5 text-right text-gray-400">n={row.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Commands reference */}
        <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-4">
            ML Pipeline Commands
          </h2>
          <div className="space-y-5 text-xs font-mono">

            {/* Authentication */}
            <div>
              <div className="text-gray-500 uppercase tracking-wider text-[10px] mb-2 font-sans font-semibold">
                ── Authentication ──
              </div>
              <div className="space-y-2">
                <div>
                  <div className="text-gray-500"># Renew Schwab OAuth token (expires every 7 days — opens browser)</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.scripts.schwab_auth</div>
                </div>
              </div>
            </div>

            {/* Data Collection */}
            <div>
              <div className="text-gray-500 uppercase tracking-wider text-[10px] mb-2 font-sans font-semibold">
                ── Data Collection ──
              </div>
              <div className="space-y-2">
                <div>
                  <div className="text-gray-500"># Check DB status</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.ml.label_outcomes --summary</div>
                </div>
                <div>
                  <div className="text-gray-500"># Snapshot data quality audit (bad-rate, distribution)</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.ml.label_outcomes --audit</div>
                </div>
                <div>
                  <div className="text-gray-500"># Preview snapshots due without writing to DB</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.ml.label_outcomes --dry-run</div>
                </div>
                <div>
                  <div className="text-gray-500"># Force-run labeler now (outside 9 AM window)</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.ml.label_outcomes</div>
                </div>
                <div>
                  <div className="text-gray-500"># Null bad snapshots + reset labels + re-label from clean data</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.ml.label_outcomes --repair</div>
                </div>
                <div>
                  <div className="text-gray-500"># Run a manual scan now (logs new candidates)</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.scripts.scheduled_scan</div>
                </div>
                <div>
                  <div className="text-gray-500"># Preview scan filters without running</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.scripts.scheduled_scan --dry-run</div>
                </div>
              </div>
            </div>

            {/* Scheduler */}
            <div>
              <div className="text-gray-500 uppercase tracking-wider text-[10px] mb-2 font-sans font-semibold">
                ── Scheduler (PowerShell) ──
              </div>
              <div className="space-y-2">
                <div>
                  <div className="text-gray-500"># Check last run result + next fire time</div>
                  <div className="text-sky-300 mt-0.5">{"Get-ScheduledTaskInfo -TaskName 'Leaps2.0 - Label Outcomes' | Select LastRunTime, LastTaskResult, NextRunTime"}</div>
                </div>
                <div>
                  <div className="text-gray-500"># Manually trigger the 9 AM scheduler task</div>
                  <div className="text-sky-300 mt-0.5">{"Start-ScheduledTask -TaskName 'Leaps2.0 - Label Outcomes'"}</div>
                </div>
              </div>
            </div>

            {/* Training */}
            <div>
              <div className="text-gray-500 uppercase tracking-wider text-[10px] mb-2 font-sans font-semibold">
                ── Training (500+ labeled rows required) ──
              </div>
              <div className="space-y-2">
                <div>
                  <div className="text-gray-500"># Train with default 50 Optuna trials</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.ml.train</div>
                </div>
                <div>
                  <div className="text-gray-500"># Train with more trials for better HPO (slower)</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.ml.train --trials 100</div>
                </div>
              </div>
            </div>

            {/* Evaluation */}
            <div>
              <div className="text-gray-500 uppercase tracking-wider text-[10px] mb-2 font-sans font-semibold">
                ── Evaluation (post-training) ──
              </div>
              <div className="space-y-2">
                <div>
                  <div className="text-gray-500"># Walk-forward backtest over a date range</div>
                  <div className="text-sky-300 mt-0.5">backend\.venv\Scripts\python.exe -m backend.ml.backtest --start 2024-01-01 --end 2025-01-01</div>
                </div>
              </div>
            </div>

          </div>
        </div>

      </div>
    </div>
  );
}
