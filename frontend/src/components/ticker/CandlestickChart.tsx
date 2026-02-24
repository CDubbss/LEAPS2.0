import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CandlestickSeries,
  type IChartApi,
  type CandlestickData,
  type Time,
} from "lightweight-charts";
import type { OHLCBar } from "@/types";
import { optionsApi } from "@/api/client";

interface Props {
  symbol: string;
}

const PERIODS = [
  { label: "1M", value: "1mo" },
  { label: "3M", value: "3mo" },
  { label: "6M", value: "6mo" },
  { label: "1Y", value: "1y" },
  { label: "2Y", value: "2y" },
] as const;

const CHART_HEIGHT = 260;

export const CandlestickChart: React.FC<Props> = ({ symbol }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const seriesRef = useRef<any>(null);
  const [period, setPeriod] = useState<string>("1y");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create chart — use autoSize so the library handles resizing via its own
  // ResizeObserver.  This avoids a 0-width chart when the Dialog hasn't yet
  // completed its layout pass.
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,          // fills the CSS-sized container automatically
      layout: {
        background: { type: ColorType.Solid, color: "#111827" },
        textColor: "#9ca3af",
      },
      grid: {
        vertLines: { color: "#1f2937" },
        horzLines: { color: "#1f2937" },
      },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: "#374151" },
      timeScale: { borderColor: "#374151", timeVisible: true },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderUpColor: "#22c55e",
      borderDownColor: "#ef4444",
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Fetch OHLC data whenever symbol or period changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    optionsApi.getHistoricalOHLC(symbol, period)
      .then((bars: OHLCBar[]) => {
        if (cancelled) return;
        if (!seriesRef.current) return;
        const data: CandlestickData<Time>[] = bars.map((b) => ({
          time: b.time as Time,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }));
        seriesRef.current.setData(data);
        chartRef.current?.timeScale().fitContent();
        setLoading(false);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message || "Failed to load chart data");
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [symbol, period]);

  return (
    <div className="space-y-2">
      {/* Timeline buttons */}
      <div className="flex gap-1">
        {PERIODS.map((p) => (
          <button
            key={p.value}
            onClick={() => setPeriod(p.value)}
            className={`px-2 py-0.5 rounded text-xs font-medium transition-colors ${
              period === p.value
                ? "bg-sky-600 text-white"
                : "bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-white"
            }`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* Chart container — explicit CSS height so autoSize fills it correctly */}
      <div className="relative" style={{ height: CHART_HEIGHT }}>
        <div
          ref={containerRef}
          className="w-full h-full rounded overflow-hidden"
        />
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/70 rounded">
            <span className="text-xs text-gray-400">Loading chart…</span>
          </div>
        )}
        {error && !loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-900/70 rounded">
            <span className="text-xs text-red-400">{error}</span>
          </div>
        )}
      </div>
    </div>
  );
};
