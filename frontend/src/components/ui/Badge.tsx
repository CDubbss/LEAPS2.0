/**
 * Badge — inline label chip.
 *
 * Variants:
 *   sky      → accent (active filters, active nav)
 *   green    → calls / positive
 *   red      → puts / negative
 *   orange   → warning / fundamentals
 *   gray     → neutral / default
 *
 * To restyle all badges: change the variant map below.
 */
import React from "react";
import { cn } from "@/utils/cn";

type BadgeVariant = "sky" | "green" | "red" | "orange" | "gray";

interface BadgeProps {
  variant?: BadgeVariant;
  className?: string;
  children: React.ReactNode;
}

const variants: Record<BadgeVariant, string> = {
  sky:    "bg-sky-900/60 text-sky-300 border border-sky-700",
  green:  "bg-green-900/60 text-green-300 border border-green-700",
  red:    "bg-red-900/60 text-red-300 border border-red-700",
  orange: "bg-orange-900/60 text-orange-300 border border-orange-700",
  gray:   "bg-gray-700 text-gray-300 border border-gray-600",
};

export const Badge: React.FC<BadgeProps> = ({
  variant = "gray",
  className,
  children,
}) => (
  <span
    className={cn(
      "inline-flex items-center px-2 py-0.5 rounded text-xs font-medium",
      variants[variant],
      className
    )}
  >
    {children}
  </span>
);
