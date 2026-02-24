import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { ScannerPage } from "@/pages/ScannerPage";
import { OptionsChainPage } from "@/pages/OptionsChainPage";
import { ScanIcon, Link } from "lucide-react";
import "./index.css";

function App() {
  return (
    <TooltipProvider delayDuration={300}>
    <BrowserRouter>
      <div className="flex flex-col h-screen bg-gray-950 text-white">
        {/* Top Nav */}
        <nav className="flex items-center gap-1 px-4 py-2 bg-gray-900 border-b border-gray-700 flex-shrink-0">
          <div className="flex items-center gap-2 mr-4 lg:mr-6">
            <ScanIcon size={20} className="text-sky-400" />
            <span className="hidden sm:inline text-lg font-bold text-white">Leaps2.0</span>
            <span className="hidden lg:inline text-xs text-gray-500 ml-1">Options Scanner</span>
          </div>
          <NavLink
            to="/"
            end
            className={({ isActive }) =>
              `px-3 py-1.5 text-sm rounded-md transition-colors ${
                isActive
                  ? "bg-sky-700 text-white"
                  : "text-gray-400 hover:text-white hover:bg-gray-700"
              }`
            }
          >
            Scanner
          </NavLink>
          <NavLink
            to="/chain"
            className={({ isActive }) =>
              `px-3 py-1.5 text-sm rounded-md transition-colors ${
                isActive
                  ? "bg-sky-700 text-white"
                  : "text-gray-400 hover:text-white hover:bg-gray-700"
              }`
            }
          >
            <span className="sm:hidden">Chain</span>
            <span className="hidden sm:inline">Options Chain</span>
          </NavLink>
        </nav>

        {/* Page content */}
        <div className="flex-1 overflow-hidden">
          <Routes>
            <Route path="/" element={<ScannerPage />} />
            <Route path="/chain" element={<OptionsChainPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
    </TooltipProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
