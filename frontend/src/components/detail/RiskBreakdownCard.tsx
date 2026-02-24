import React from "react";
import type { RiskScore } from "@/types";
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  Radar,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { scoreColor } from "@/utils/formatting";
import { ShieldCheck } from "lucide-react";
import { InfoTooltip } from "@/components/ui/Tooltip";
import { TOOLTIPS } from "@/utils/tooltips";

interface Props {
  riskScore: RiskScore;
}

const DIMENSION_LABELS: Record<string, string> = {
  iv_rank: "IV Rank",
  bid_ask: "Bid-Ask",
  fundamental: "Fundamental",
  sentiment: "Sentiment",
  liquidity: "Liquidity",
};

const DIMENSION_TOOLTIPS: Record<string, string> = {
  iv_rank: TOOLTIPS.iv_risk,
  bid_ask: TOOLTIPS.ba_risk,
  fundamental: TOOLTIPS.fund_risk,
  sentiment: TOOLTIPS.sent_risk,
  liquidity: TOOLTIPS.liq_risk,
};

export const RiskBreakdownCard: React.FC<Props> = ({ riskScore }) => {
  const radarData = Object.entries(riskScore.breakdown).map(([key, value]) => ({
    dimension: DIMENSION_LABELS[key] || key,
    score: Number(value.toFixed(1)),
    fullMark: 100,
  }));

  const score = riskScore.composite_score;

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} className="text-green-400" />
          <h3 className="text-sm font-semibold text-white">Risk Breakdown</h3>
        </div>
        <div className="text-right">
          <span className={`text-xl font-bold ${scoreColor(score)}`}>
            {score.toFixed(1)}
          </span>
          <div className="text-xs text-gray-400">
            Composite <InfoTooltip content={TOOLTIPS.composite} />
          </div>
        </div>
      </div>

      <ResponsiveContainer width="100%" height={200}>
        <RadarChart data={radarData}>
          <PolarGrid stroke="#374151" />
          <PolarAngleAxis
            dataKey="dimension"
            tick={{ fontSize: 10, fill: "#9ca3af" }}
          />
          <Radar
            name="Score"
            dataKey="score"
            stroke="#0ea5e9"
            fill="#0ea5e9"
            fillOpacity={0.25}
          />
          <Tooltip
            contentStyle={{
              background: "#1f2937",
              border: "1px solid #374151",
              borderRadius: 4,
              fontSize: 11,
              color: "#fff",
            }}
          />
        </RadarChart>
      </ResponsiveContainer>

      {/* Component breakdown */}
      <div className="space-y-1.5">
        {Object.entries(riskScore.breakdown).map(([key, value]) => (
          <div key={key} className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-28">
              {DIMENSION_LABELS[key] || key}
              {DIMENSION_TOOLTIPS[key] && (
                <InfoTooltip content={DIMENSION_TOOLTIPS[key]} />
              )}
            </span>
            <div className="flex-1 bg-gray-700 rounded-full h-1.5">
              <div
                className={`h-1.5 rounded-full ${
                  value >= 70
                    ? "bg-green-500"
                    : value >= 50
                    ? "bg-yellow-500"
                    : "bg-red-500"
                }`}
                style={{ width: `${value}%` }}
              />
            </div>
            <span className={`text-xs font-medium w-8 text-right ${scoreColor(value)}`}>
              {value.toFixed(0)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
};
