/**
 * Navigation config — single source of truth for all tabs/routes.
 *
 * HOW TO ADD A NEW TAB:
 *   1. Import an icon from lucide-react below.
 *   2. Append one object to NAV_ITEMS.
 *   3. Add the <Route> in main.tsx.
 *   That's it — both TopNav and BottomTabBar render from this array.
 *
 * Fields:
 *   path      → React Router path
 *   label     → display name (used in both navs)
 *   shortLabel → compact label for bottom bar on very small screens (optional)
 *   Icon      → Lucide icon component
 *   end       → pass `end` to NavLink (exact match, for "/")
 */
import { ScanSearch, Link2, BrainCircuit } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  path: string;
  label: string;
  shortLabel?: string;
  Icon: LucideIcon;
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: "/",
    label: "Scanner",
    Icon: ScanSearch,
    end: true,
  },
  {
    path: "/chain",
    label: "Options Chain",
    shortLabel: "Chain",
    Icon: Link2,
  },
  {
    path: "/ml",
    label: "ML Dashboard",
    shortLabel: "ML",
    Icon: BrainCircuit,
  },
];
