/**
 * Sheet — bottom slide-up panel.
 *
 * Used for: filter drawer (mobile), spread detail, any modal-like overlay.
 *
 * Props:
 *   open        → controls visibility
 *   onClose     → called when backdrop or close button is tapped
 *   title       → optional header text
 *   maxHeight   → Tailwind max-h class (default "max-h-[85vh]")
 *   children    → scrollable body content
 *
 * To restyle: change the className strings below or the tokens in theme/ui.ts.
 */
import React from "react";
import { X } from "lucide-react";
import { cn } from "@/utils/cn";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title?: React.ReactNode;
  maxHeight?: string;
  /** Extra class on the panel itself */
  className?: string;
  children: React.ReactNode;
}

export const Sheet: React.FC<SheetProps> = ({
  open,
  onClose,
  title,
  maxHeight = "max-h-[85vh]",
  className,
  children,
}) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        className={cn(
          "absolute bottom-0 left-0 right-0 flex flex-col",
          "bg-gray-900 rounded-t-2xl border-t border-gray-700 shadow-2xl",
          maxHeight,
          className
        )}
      >
        {/* Drag handle */}
        <div className="flex justify-center pt-2 pb-1 flex-shrink-0">
          <div className="w-10 h-1 bg-gray-600 rounded-full" />
        </div>

        {/* Header */}
        {title && (
          <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700 flex-shrink-0">
            <span className="text-sm font-semibold text-white">{title}</span>
            <button
              onClick={onClose}
              className="p-1 text-gray-400 hover:text-white transition-colors"
              aria-label="Close"
            >
              <X size={16} />
            </button>
          </div>
        )}

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
};
