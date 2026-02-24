import React, { useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import type { ArticleSentiment } from "@/types";
import { X, ExternalLink } from "lucide-react";

interface Props {
  articles: ArticleSentiment[];
  symbol: string;
}

type Filter = "all" | "positive" | "neutral" | "negative";

const FILTERS: { label: string; value: Filter }[] = [
  { label: "All", value: "all" },
  { label: "Positive", value: "positive" },
  { label: "Neutral", value: "neutral" },
  { label: "Negative", value: "negative" },
];

const LABEL_COLORS: Record<string, string> = {
  positive: "bg-green-900/50 text-green-400 border border-green-700/50",
  neutral: "bg-gray-700/50 text-gray-400 border border-gray-600/50",
  negative: "bg-red-900/50 text-red-400 border border-red-700/50",
};

export const SentimentArticleList: React.FC<Props> = ({ articles, symbol }) => {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

  const filtered = articles
    .filter((a) => filter === "all" || a.label === filter)
    .sort((a, b) => Math.abs(b.positive - b.negative) - Math.abs(a.positive - a.negative));

  const counts = {
    all: articles.length,
    positive: articles.filter((a) => a.label === "positive").length,
    neutral: articles.filter((a) => a.label === "neutral").length,
    negative: articles.filter((a) => a.label === "negative").length,
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="text-xs text-sky-400 hover:text-sky-300 hover:underline"
      >
        View all {articles.length} articles →
      </button>

      <Dialog.Root open={open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/60 z-40" />
          <Dialog.Content
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50
                       bg-gray-900 border border-gray-700 rounded-xl shadow-2xl
                       w-[min(90vw,640px)] max-h-[80vh] flex flex-col"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-4 border-b border-gray-700 flex-shrink-0">
              <Dialog.Title className="text-base font-semibold text-white">
                News Sentiment — {symbol}
              </Dialog.Title>
              <button
                onClick={() => setOpen(false)}
                className="text-gray-500 hover:text-gray-300"
              >
                <X size={18} />
              </button>
            </div>

            {/* Filter tabs */}
            <div className="flex gap-1 p-3 border-b border-gray-700 flex-shrink-0">
              {FILTERS.map((f) => (
                <button
                  key={f.value}
                  onClick={() => setFilter(f.value)}
                  className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                    filter === f.value
                      ? "bg-sky-600 text-white"
                      : "bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-white"
                  }`}
                >
                  {f.label}
                  <span className="ml-1 opacity-60">({counts[f.value]})</span>
                </button>
              ))}
            </div>

            {/* Article list */}
            <div className="overflow-y-auto flex-1 p-3 space-y-2">
              {filtered.length === 0 ? (
                <p className="text-xs text-gray-500 text-center py-4">No articles in this category.</p>
              ) : (
                filtered.map((article, i) => (
                  <ArticleRow key={i} article={article} />
                ))
              )}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
};

const ArticleRow: React.FC<{ article: ArticleSentiment }> = ({ article }) => {
  const total = article.positive + article.neutral + article.negative || 1;
  const posW = (article.positive / total) * 100;
  const neuW = (article.neutral / total) * 100;
  const negW = (article.negative / total) * 100;

  // Format date nicely
  let dateStr = article.published_at;
  if (dateStr) {
    try {
      dateStr = new Date(dateStr).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      // keep raw string
    }
  }

  return (
    <div className="bg-gray-800 rounded-lg p-3 space-y-2">
      {/* Headline row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          {article.url ? (
            <a
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-gray-200 hover:text-sky-400 leading-relaxed flex gap-1 items-start"
            >
              <span className="flex-1">{article.headline}</span>
              <ExternalLink size={10} className="flex-shrink-0 mt-0.5 opacity-60" />
            </a>
          ) : (
            <span className="text-xs text-gray-200 leading-relaxed">{article.headline}</span>
          )}
        </div>
        <span
          className={`flex-shrink-0 text-xs px-1.5 py-0.5 rounded capitalize ${
            LABEL_COLORS[article.label] ?? LABEL_COLORS.neutral
          }`}
        >
          {article.label}
        </span>
      </div>

      {/* Meta */}
      {(article.source || dateStr) && (
        <div className="text-xs text-gray-500">
          {article.source}{article.source && dateStr ? " · " : ""}{dateStr}
        </div>
      )}

      {/* Score bars */}
      <div className="flex gap-0.5 h-1.5 rounded overflow-hidden">
        <div className="bg-green-500 rounded-l" style={{ width: `${posW}%` }} title={`Positive ${(article.positive * 100).toFixed(0)}%`} />
        <div className="bg-gray-500" style={{ width: `${neuW}%` }} title={`Neutral ${(article.neutral * 100).toFixed(0)}%`} />
        <div className="bg-red-500 rounded-r" style={{ width: `${negW}%` }} title={`Negative ${(article.negative * 100).toFixed(0)}%`} />
      </div>
      <div className="flex gap-3 text-xs text-gray-500">
        <span className="text-green-400">{(article.positive * 100).toFixed(0)}% pos</span>
        <span className="text-gray-400">{(article.neutral * 100).toFixed(0)}% neu</span>
        <span className="text-red-400">{(article.negative * 100).toFixed(0)}% neg</span>
      </div>
    </div>
  );
};
