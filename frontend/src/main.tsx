/**
 * App shell — router, nav, page layout.
 *
 * Mobile  (< lg): TopNav (logo only) + BottomTabBar (tab routing)
 * Desktop (≥ lg): TopNav (logo + nav links), no bottom bar
 *
 * To add a new page:
 *   1. Create the page component in pages/.
 *   2. Add its route to nav/config.ts (adds it to both navs automatically).
 *   3. Add a <Route> below.
 */
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { ScannerPage }      from "@/pages/ScannerPage";
import { OptionsChainPage } from "@/pages/OptionsChainPage";
import { MLDashboardPage }  from "@/pages/MLDashboardPage";
import { TopNav }           from "@/components/nav/TopNav";
import { BottomTabBar }     from "@/components/nav/BottomTabBar";
import "./index.css";

function App() {
  return (
    <TooltipProvider delayDuration={300}>
      <BrowserRouter>
        <div className="flex flex-col h-screen bg-gray-950 text-white">

          {/* Top nav — logo on mobile, logo + links on desktop */}
          <TopNav />

          {/* Page content — flex-1 so it fills remaining height */}
          <div className="flex-1 overflow-hidden">
            <Routes>
              <Route path="/"      element={<ScannerPage />}      />
              <Route path="/chain" element={<OptionsChainPage />} />
              <Route path="/ml"    element={<MLDashboardPage />}  />
            </Routes>
          </div>

          {/* Bottom tab bar — mobile only (hidden on lg+) */}
          <BottomTabBar />

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
