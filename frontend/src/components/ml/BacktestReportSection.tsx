/**
 * BacktestReportSection — renders the walk-forward backtest report on the
 * ML Dashboard. Data comes from GET /ml/backtest-report, which serves the
 * artifact written by `python -m backend.ml.backtest --json`.
 *
 * Shows: edge-vs-random headline, decile lift bars, time-matched hit-rate
 * table, and calibration. Charts are plain Tailwind divs (no chart lib).
 */
import React, { useEffect, useState } from "react";
import axios from "axios";

type DecileRow = {
  decile: number;
  n: number;
  ml_score_mean: number;
  outcome_mean: number;
  outcome_median: number;
  peak_pnl_mean: number;
  win_rate: number | null;
  n_decided: number;
};

type HitRateRow = { quintile: number; n: number; hit_rate: number };

type BacktestReport = {
  generated_at: string;
  since: string | null;
  n_rows: number;
  n_labeled: number;
  decile_lift: DecileRow[];
  correlations: {
    overall: { rho: number; p: number; n: number } | null;
    by_tier: Record<string, { rho: number; n: number }>;
    by_month: Record<string, { rho: number; n: number }>;
  };
  hit_rates: Record<string, HitRateRow[]>;
  simulation: {
    top_k: number;
    model: {
      n_trades: number;
      total_pnl: number;
      win_rate: number | null;
      avg_days_held: number | null;
      max_drawdown: number;
      unrealized_positions: number;
    };
    random_baseline: {
      iterations: number;
      mean_total_pnl: number;
      std_total_pnl: number;
      mean_win_rate: number | null;
    };
  };
};

const dollars = (v: number) =>
  `${v < 0 ? "-" : ""}$${Math.abs(Math.round(v)).toLocaleString()}`;

export function BacktestReportSection() {
  const [report, setReport] = useState<BacktestReport | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    axios
      .get<BacktestReport>("/api/v1/ml/backtest-report")
      .then((r) => setReport(r.data))
      .catch(() => setMissing(true));
  }, []);

  if (missing) {
    return (
      <div className="bg-gray-800 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-200 mb-1">
          Backtest Report
        </h2>
        <p className="text-xs text-gray-500">
          No report generated yet. Run{" "}
          <code className="text-sky-300 font-mono">
            python -m backend.ml.backtest --json
          </code>{" "}
          and refresh.
        </p>
      </div>
    );
  }
  if (!report) return null;

  const sim = report.simulation;
  const edge = sim.model.total_pnl - sim.random_baseline.mean_total_pnl;
  const horizons = Object.keys(report.hit_rates).sort(
    (a, b) => Number(a) - Number(b)
  );
  const quintiles = [1, 2, 3, 4, 5];
  const maxOutcome = Math.max(
    ...report.decile_lift.map((d) => d.outcome_mean),
    1
  );
  const lift =
    report.decile_lift.length >= 2
      ? report.decile_lift[report.decile_lift.length - 1].outcome_mean -
        report.decile_lift[0].outcome_mean
      : 0;

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-4">
      <div className="flex items-baseline justify-between flex-wrap gap-1">
        <h2 className="text-sm font-semibold text-gray-200">
          Backtest Report{" "}
          <span className="text-gray-500 font-normal">
            (out-of-sample, scan-time scores)
          </span>
        </h2>
        <span className="text-[10px] text-gray-500">
          generated {report.generated_at}
          {report.since ? ` · since ${report.since}` : " · all data"} ·{" "}
          {report.n_labeled.toLocaleString()} labeled rows
        </span>
      </div>

      {/* Headline cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-gray-900/60 rounded p-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">
            Edge vs Random
          </div>
          <div
            className={`text-xl font-bold ${edge >= 0 ? "text-green-400" : "text-red-400"}`}
          >
            {edge >= 0 ? "+" : ""}
            {dollars(edge)}
          </div>
          <div className="text-[10px] text-gray-500">
            top-{sim.top_k}/day sim, {sim.model.n_trades} trades
          </div>
        </div>
        <div className="bg-gray-900/60 rounded p-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">
            Sim Win Rate
          </div>
          <div className="text-xl font-bold text-white">
            {sim.model.win_rate != null
              ? `${(sim.model.win_rate * 100).toFixed(0)}%`
              : "—"}
          </div>
          <div className="text-[10px] text-gray-500">
            random: {sim.random_baseline.mean_win_rate != null
              ? `${(sim.random_baseline.mean_win_rate * 100).toFixed(0)}%`
              : "—"}
          </div>
        </div>
        <div className="bg-gray-900/60 rounded p-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">
            Decile Lift
          </div>
          <div
            className={`text-xl font-bold ${lift >= 0 ? "text-green-400" : "text-red-400"}`}
          >
            {lift >= 0 ? "+" : ""}
            {lift.toFixed(1)} pts
          </div>
          <div className="text-[10px] text-gray-500">top vs bottom decile</div>
        </div>
        <div className="bg-gray-900/60 rounded p-3">
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">
            Max Drawdown
          </div>
          <div className="text-xl font-bold text-amber-400">
            {dollars(sim.model.max_drawdown)}
          </div>
          <div className="text-[10px] text-gray-500">
            {sim.model.unrealized_positions} positions still open
          </div>
        </div>
      </div>

      {/* Decile lift bars */}
      <div>
        <div className="text-xs text-gray-400 mb-2">
          Realized outcome by ML-score decile (1 = lowest scores, 10 = highest)
        </div>
        <div className="flex items-end gap-1 h-24">
          {report.decile_lift.map((d) => (
            <div
              key={d.decile}
              className="flex-1 flex flex-col items-center gap-1"
              title={`Decile ${d.decile}: predicted ${d.ml_score_mean}, realized ${d.outcome_mean} (n=${d.n})`}
            >
              <div className="text-[9px] text-gray-400 font-mono">
                {d.outcome_mean.toFixed(0)}
              </div>
              <div
                className={`w-full rounded-t ${
                  d.decile === 10 ? "bg-green-500" : "bg-sky-700"
                }`}
                style={{
                  height: `${Math.max(4, (d.outcome_mean / maxOutcome) * 100)}%`,
                }}
              />
              <div className="text-[9px] text-gray-500">{d.decile}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Hit-rate table */}
      {horizons.length > 0 && (
        <div>
          <div className="text-xs text-gray-400 mb-2">
            P(hit +50% target within N days) by score quintile — censoring-safe
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-700">
                <th className="text-left py-1.5 font-medium">Quintile</th>
                {horizons.map((h) => (
                  <th key={h} className="text-right py-1.5 font-medium">
                    ≤{h}d
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {quintiles.map((q) => (
                <tr key={q} className="border-b border-gray-700/50">
                  <td className="py-1.5 text-gray-300">
                    {q === 5 ? "5 (best)" : q === 1 ? "1 (worst)" : q}
                  </td>
                  {horizons.map((h) => {
                    const row = report.hit_rates[h].find(
                      (r) => r.quintile === q
                    );
                    const v = row ? row.hit_rate : null;
                    return (
                      <td
                        key={h}
                        className={`py-1.5 text-right font-mono ${
                          v == null
                            ? "text-gray-600"
                            : v >= 0.5
                              ? "text-green-400 font-semibold"
                              : v >= 0.2
                                ? "text-sky-300"
                                : "text-gray-400"
                        }`}
                        title={row ? `n=${row.n}` : undefined}
                      >
                        {v != null ? `${(v * 100).toFixed(1)}%` : "—"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[10px] text-gray-600">
        Scores are ordinal, not calibrated — trust the ranking, not the
        absolute number. Mature label tiers (60d+) carry the real signal;
        young rows only have noisy short-horizon labels.
      </p>
    </div>
  );
}
