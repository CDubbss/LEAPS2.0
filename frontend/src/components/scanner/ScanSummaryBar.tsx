import React from "react";
import type { ScannerResult } from "@/types";
import { formatDate } from "@/utils/formatting";
import { Clock, BarChart2, CheckCircle } from "lucide-react";

interface Props {
  result: ScannerResult;
}

export const ScanSummaryBar: React.FC<Props> = ({ result }) => {
  return (
    <div className="flex items-center gap-6 px-4 py-3 bg-gray-800 border-b border-gray-700 text-sm">
      <div className="flex items-center gap-2 text-gray-300">
        <BarChart2 size={16} className="text-sky-400" />
        <span>
          <span className="text-white font-semibold">
            {result.total_candidates_evaluated.toLocaleString()}
          </span>{" "}
          candidates evaluated
        </span>
      </div>
      <div className="flex items-center gap-2 text-gray-300">
        <CheckCircle size={16} className="text-green-400" />
        <span>
          <span className="text-white font-semibold">
            {result.results.length}
          </span>{" "}
          passed filters
        </span>
      </div>
      <div className="flex items-center gap-2 text-gray-300">
        <Clock size={16} className="text-gray-400" />
        <span>{result.scan_duration_seconds.toFixed(1)}s</span>
      </div>
      <div className="ml-auto text-gray-500 text-xs">
        Scanned {formatDate(result.scan_time)}
      </div>
    </div>
  );
};
