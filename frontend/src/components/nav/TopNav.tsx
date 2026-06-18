/**
 * TopNav — desktop navigation bar (hidden on mobile, bottom bar takes over).
 *
 * On desktop (≥ lg): shows logo + nav links horizontally.
 * On mobile (< lg):  shows logo only (bottom bar handles routing).
 *
 * To restyle:
 *   • Bar background/border: change className on <nav>.
 *   • Active pill:           change activeClass.
 *   • Inactive pill:         change inactiveClass.
 *   • Logo icon/text:        edit the Logo section below.
 *   • Add/remove tabs:       edit nav/config.ts only.
 */
import React from "react";
import { NavLink } from "react-router-dom";
import { ScanIcon } from "lucide-react";
import { NAV_ITEMS } from "./config";
import { cn } from "@/utils/cn";

const activeClass   = "bg-sky-700 text-white";
const inactiveClass = "text-gray-400 hover:text-white hover:bg-gray-700";

export const TopNav: React.FC = () => (
  <nav className="flex items-center gap-1 px-4 py-2 bg-gray-900 border-b border-gray-700 flex-shrink-0">
    {/* Logo */}
    <div className="flex items-center gap-2 mr-4">
      <ScanIcon size={20} className="text-sky-400" />
      <span className="text-lg font-bold text-white">Leaps2.0</span>
      <span className="hidden lg:inline text-xs text-gray-500 ml-1">
        Options Scanner
      </span>
    </div>

    {/* Nav links — visible on desktop only */}
    {NAV_ITEMS.map(({ path, label, shortLabel, end }) => (
      <NavLink
        key={path}
        to={path}
        end={end}
        className={({ isActive }) =>
          cn(
            "hidden lg:inline-flex px-3 py-1.5 text-sm rounded-md transition-colors",
            isActive ? activeClass : inactiveClass
          )
        }
      >
        {label}
      </NavLink>
    ))}

    {/* Mobile: active page name (right-aligned) */}
    <div className="lg:hidden ml-auto">
      {NAV_ITEMS.map(({ path, shortLabel, label, end }) => (
        <NavLink
          key={path}
          to={path}
          end={end}
          className={({ isActive }) =>
            isActive ? "text-sm font-medium text-sky-400" : "hidden"
          }
        >
          {shortLabel ?? label}
        </NavLink>
      ))}
    </div>
  </nav>
);
