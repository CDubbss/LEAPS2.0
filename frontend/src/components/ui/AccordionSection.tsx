/**
 * AccordionSection — collapsible filter/content group.
 *
 * Used in: FilterPanel (each filter group), MLDashboard sections.
 *
 * Props:
 *   title       → section header label
 *   badge       → optional count/status badge next to title
 *   defaultOpen → starts expanded (default: true)
 *   children    → section body content
 *
 * To restyle headers globally: edit the className strings below.
 */
import React, { useState } from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/utils/cn";

interface AccordionSectionProps {
  title: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
  /** Extra class on the outer wrapper */
  className?: string;
}

export const AccordionSection: React.FC<AccordionSectionProps> = ({
  title,
  badge,
  defaultOpen = true,
  children,
  className,
}) => {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={cn("border-b border-gray-700 last:border-b-0", className)}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between w-full px-4 py-3 text-sm font-medium text-gray-300 hover:bg-gray-800/60 transition-colors select-none"
      >
        <span className="flex items-center gap-2">
          {title}
          {badge}
        </span>
        <ChevronDown
          size={14}
          className={cn(
            "text-gray-500 transition-transform duration-200",
            open && "rotate-180"
          )}
        />
      </button>

      {open && (
        <div className="px-4 pb-4 pt-1 space-y-3">{children}</div>
      )}
    </div>
  );
};
