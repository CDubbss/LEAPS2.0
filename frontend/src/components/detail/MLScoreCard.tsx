import React from "react";
import type { MLPrediction } from "@/types";
import { BarChart, Bar, XAxis, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { scoreColor, scoreBackground, formatPct } from "@/utils/formatting";
import { BrainCircuit } from "lucide-react";
import { InfoTooltip } from "@/components/ui/Tooltip";
import { TOOLTIPS } from "@/utils/tooltips";

interface Props {
  prediction: MLPrediction;
}

export const MLScoreCard: React.FC<Props> = ({ prediction }) => {
  const score = prediction.spread_quality_score;

  // Top feature importances for chart
  const importanceData = Object.entries(prediction.feature_importances)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 8)
    .map(([name, value]) => ({
      name: name.replace(/_/g, " "),
      value: Number((value * 100).toFixed(1)),
    }));

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center gap-2">
        <BrainCircuit size={18} className="text-purple-400" />
        <h3 className="text-sm font-semibold text-white">ML Analysis</h3>
        {prediction.is_placeholder && (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 bg-yellow-800 text-yellow-300 text-xs rounded">
            Placeholder
            <InfoTooltip content={TOOLTIPS.ml_placeholder} />
          </span>
        )}
      </div>

      {/* Score display */}
      <div className="flex items-center gap-4">
        <div className="relative w-20 h-20">
          <svg className="w-20 h-20 -rotate-90" viewBox="0 0 36 36">
            <circle
              cx="18"
              cy="18"
              r="15.9"
              fill="none"
              stroke="#374151"
              strokeWidth="3"
            />
            <circle
              cx="18"
              cy="18"
              r="15.9"
              fill="none"
              stroke={score >= 70 ? "#22c55e" : score >= 50 ? "#eab308" : "#ef4444"}
              strokeWidth="3"
              strokeDasharray={`${score} ${100 - score}`}
              strokeLinecap="round"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className={`text-lg font-bold ${scoreColor(score)}`}>
              {score.toFixed(0)}
            </span>
          </div>
        </div>
        <div className="space-y-1">
          <div className="text-xs text-gray-400">Quality Score</div>
          <div className="text-sm text-gray-300">
            Est. Return:{" "}
            <span className={prediction.expected_return_pct >= 0 ? "text-green-400" : "text-red-400"}>
              {prediction.expected_return_pct >= 0 ? "+" : ""}
              {prediction.expected_return_pct.toFixed(1)}%
            </span>
          </div>
          <div className="text-sm text-gray-300">
            ML PoP:{" "}
            <span className="text-gray-200">
              {formatPct(prediction.probability_of_profit)}
            </span>
          </div>
          <div className="text-xs text-gray-500">
            Confidence: {(prediction.confidence * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      {/* Feature importance chart */}
      {importanceData.length > 0 && (
        <div>
          <div className="text-xs text-gray-400 mb-2">Feature Importances</div>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart
              data={importanceData}
              layout="vertical"
              margin={{ left: 0, right: 20, top: 0, bottom: 0 }}
            >
              <XAxis type="number" tick={{ fontSize: 10, fill: "#9ca3af" }} unit="%" />
              <Tooltip
                contentStyle={{
                  background: "#1f2937",
                  border: "1px solid #374151",
                  borderRadius: 4,
                  fontSize: 11,
                  color: "#fff",
                }}
                formatter={(v) => [`${v}%`, "Importance"]}
              />
              <Bar dataKey="value" radius={[0, 2, 2, 0]}>
                {importanceData.map((_, i) => (
                  <Cell
                    key={i}
                    fill={`hsl(${200 + i * 15}, 70%, 55%)`}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {prediction.is_placeholder && (
        <p className="text-xs text-yellow-500/80">
          ML model not yet trained. Run scans daily to collect data, then
          train with: <code className="font-mono">python -m backend.ml.train</code>
        </p>
      )}
    </div>
  );
};
