/**
 * BottomTabBar — mobile-only bottom navigation.
 *
 * Visible only on screens < lg (1024px).
 * Sits in a fixed position at bottom; content areas add pb-16 to avoid overlap.
 *
 * To restyle:
 *   • Background/border: change className on the <nav> below.
 *   • Active color:      change activeClass.
 *   • Inactive color:    change inactiveClass.
 *   • Height:            change h-16 (also update size.bottomBar in theme/ui.ts).
 *   • Add/remove tabs:   edit nav/config.ts only.
 */
import React from "react";
import { NavLink } from "react-router-dom";
import { NAV_ITEMS } from "./config";
import { cn } from "@/utils/cn";

const activeClass   = "text-sky-400";
const inactiveClass = "text-gray-500 hover:text-gray-300";

export const BottomTabBar: React.FC = () => (
  <nav className="lg:hidden fixed bottom-0 left-0 right-0 z-40 h-16 bg-gray-900 border-t border-gray-700 flex items-stretch">
    {NAV_ITEMS.map(({ path, label, shortLabel, Icon, end }) => (
      <NavLink
        key={path}
        to={path}
        end={end}
        className={({ isActive }) =>
          cn(
            "flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition-colors",
            isActive ? activeClass : inactiveClass
          )
        }
      >
        {({ isActive }) => (
          <>
            <Icon size={20} strokeWidth={isActive ? 2.5 : 1.75} />
            <span>{shortLabel ?? label}</span>
          </>
        )}
      </NavLink>
    ))}
  </nav>
);
