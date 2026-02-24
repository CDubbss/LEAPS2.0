/**
 * Formatting utilities for options data display.
 */

export function formatCurrency(value: number, decimals = 2): string {
  return `$${value.toFixed(decimals)}`;
}

export function formatPct(value: number, decimals = 1): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

export function formatScore(score: number): string {
  return score.toFixed(1);
}

export function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDTE(dte: number): string {
  if (dte >= 365) return `${Math.round(dte / 30)}mo`;
  return `${dte}d`;
}

export function formatIV(iv: number): string {
  return `${(iv * 100).toFixed(1)}%`;
}

export function formatGreek(value: number, decimals = 4): string {
  return value.toFixed(decimals);
}

export function formatMarketCap(cap: number): string {
  if (cap >= 1e12) return `$${(cap / 1e12).toFixed(1)}T`;
  if (cap >= 1e9) return `$${(cap / 1e9).toFixed(1)}B`;
  if (cap >= 1e6) return `$${(cap / 1e6).toFixed(1)}M`;
  return `$${cap.toFixed(0)}`;
}

export function scoreColor(score: number): string {
  if (score >= 70) return "text-green-400";
  if (score >= 50) return "text-yellow-400";
  return "text-red-400";
}

export function scoreBackground(score: number): string {
  if (score >= 70) return "bg-green-500";
  if (score >= 50) return "bg-yellow-500";
  return "bg-red-500";
}

export function sentimentColor(label: string): string {
  if (label === "positive") return "text-green-400";
  if (label === "negative") return "text-red-400";
  return "text-gray-400";
}

export function spreadTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    bull_call: "Bull Call",
    bear_put: "Bear Put",
    leap_call: "LEAPS Call",
    leap_put: "LEAPS Put",
  };
  return labels[type] || type;
}

export function spreadTypeBadgeColor(type: string): string {
  const colors: Record<string, string> = {
    bull_call: "bg-emerald-600 text-white",
    bear_put: "bg-rose-600 text-white",
    leap_call: "bg-blue-600 text-white",
    leap_put: "bg-purple-600 text-white",
  };
  return colors[type] || "bg-gray-600 text-white";
}
