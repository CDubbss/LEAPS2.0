import React from "react";
import type { TickerSentiment } from "@/types";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { sentimentColor, scoreColor } from "@/utils/formatting";
import { Newspaper } from "lucide-react";
import { SentimentArticleList } from "./SentimentArticleList";

interface Props {
  sentiment: TickerSentiment;
}

export const SentimentScoreCard: React.FC<Props> = ({ sentiment }) => {
  const score = sentiment.sentiment_score;

  const barData = [
    { name: "Positive", value: Number((sentiment.avg_positive * 100).toFixed(1)), fill: "#22c55e" },
    { name: "Neutral", value: Number((sentiment.avg_neutral * 100).toFixed(1)), fill: "#6b7280" },
    { name: "Negative", value: Number((sentiment.avg_negative * 100).toFixed(1)), fill: "#ef4444" },
  ];

  return (
    <div className="bg-gray-800 rounded-lg p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Newspaper size={18} className="text-blue-400" />
          <h3 className="text-sm font-semibold text-white">News Sentiment</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className={`text-lg font-bold ${scoreColor(score)}`}>
            {score.toFixed(0)}
          </span>
          <span
            className={`text-xs font-medium capitalize ${sentimentColor(
              sentiment.sentiment_label
            )}`}
          >
            {sentiment.sentiment_label}
          </span>
        </div>
      </div>

      <div className="text-xs text-gray-400">
        {sentiment.articles_analyzed} articles analyzed via FinBERT
      </div>

      {/* Bar chart */}
      <ResponsiveContainer width="100%" height={80}>
        <BarChart
          data={barData}
          margin={{ top: 0, right: 0, left: 0, bottom: 0 }}
        >
          <XAxis
            dataKey="name"
            tick={{ fontSize: 10, fill: "#9ca3af" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis hide />
          <Tooltip
            contentStyle={{
              background: "#1f2937",
              border: "1px solid #374151",
              borderRadius: 4,
              fontSize: 11,
              color: "#fff",
            }}
            formatter={(v) => [`${v}%`, ""]}
          />
          <Bar dataKey="value" radius={[2, 2, 0, 0]}>
            {barData.map((d, i) => (
              <Cell key={i} fill={d.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Top headlines */}
      {sentiment.top_headlines.length > 0 && (
        <div>
          <div className="text-xs text-gray-400 mb-2">Top Headlines</div>
          <ul className="space-y-1">
            {sentiment.top_headlines.slice(0, 3).map((headline, i) => (
              <li key={i} className="text-xs text-gray-300 leading-relaxed">
                <span className="text-gray-600 mr-1">·</span>
                {headline}
              </li>
            ))}
          </ul>
        </div>
      )}

      {sentiment.articles_analyzed === 0 && (
        <p className="text-xs text-gray-500">No news articles found for this ticker.</p>
      )}

      {sentiment.article_sentiments?.length > 0 && (
        <SentimentArticleList
          articles={sentiment.article_sentiments}
          symbol={sentiment.symbol}
        />
      )}
    </div>
  );
};
