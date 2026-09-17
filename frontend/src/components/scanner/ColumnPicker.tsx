import React, { useEffect, useRef, useState } from "react";
import * as Checkbox from "@radix-ui/react-checkbox";
import { Check, Columns3, RotateCcw } from "lucide-react";

export interface PickerColumn {
  id: string;
  label: string;
  isVisible: boolean;
}

interface Props {
  columns: PickerColumn[];
  onToggle: (id: string) => void;
  onReset: () => void;
}

/**
 * Show/hide toggle for the results-table columns. Reordering is done by dragging
 * the header grips; this panel only controls visibility (+ a reset). Desktop-only —
 * the parent hides it below `lg`.
 */
export const ColumnPicker: React.FC<Props> = ({ columns, onToggle, onReset }) => {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  const visibleCount = columns.filter((c) => c.isVisible).length;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 px-2.5 py-1 text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 rounded border border-gray-700 transition-colors"
        title="Show, hide, and reorder columns"
      >
        <Columns3 size={13} />
        Columns
        <span className="text-gray-500">({visibleCount})</span>
      </button>

      {open && (
        <div className="absolute right-0 mt-1 w-56 max-h-80 overflow-y-auto bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-30 p-2">
          <div className="flex items-center justify-between px-1 pb-1.5 mb-1 border-b border-gray-700">
            <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide">
              Columns
            </span>
            <button
              onClick={onReset}
              className="flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-200"
              title="Restore default columns and order"
            >
              <RotateCcw size={11} /> Reset
            </button>
          </div>
          <p className="text-[10px] text-gray-500 px-1 pb-1.5">
            Drag a header's grip to reorder.
          </p>
          <div className="space-y-0.5">
            {columns.map((c) => (
              <label
                key={c.id}
                className="flex items-center gap-2 px-1 py-1 rounded hover:bg-gray-700/50 cursor-pointer"
              >
                <Checkbox.Root
                  checked={c.isVisible}
                  onCheckedChange={() => onToggle(c.id)}
                  className="w-4 h-4 flex-shrink-0 rounded border border-gray-600 bg-gray-900 data-[state=checked]:bg-sky-600 data-[state=checked]:border-sky-600 flex items-center justify-center"
                >
                  <Checkbox.Indicator>
                    <Check size={11} className="text-white" />
                  </Checkbox.Indicator>
                </Checkbox.Root>
                <span className="text-xs text-gray-300 truncate">{c.label}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};
