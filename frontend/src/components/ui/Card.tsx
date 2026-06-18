/**
 * Card — base surface primitive.
 *
 * Variants:
 *   default  → standard elevated card (gray-800, rounded-xl, border)
 *   flat     → no border, same bg (for nested sections)
 *   ghost    → transparent, border only
 *
 * To restyle all cards globally: edit theme/ui.ts → `card` token.
 */
import React from "react";
import { cn } from "@/utils/cn";

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "flat" | "ghost";
  noPadding?: boolean;
}

export const Card: React.FC<CardProps> = ({
  variant = "default",
  noPadding = false,
  className,
  children,
  ...props
}) => {
  const base = "rounded-xl";
  const variants = {
    default: "bg-gray-800 border border-gray-700",
    flat:    "bg-gray-800",
    ghost:   "bg-transparent border border-gray-700",
  };
  const padding = noPadding ? "" : "p-3";

  return (
    <div className={cn(base, variants[variant], padding, className)} {...props}>
      {children}
    </div>
  );
};
