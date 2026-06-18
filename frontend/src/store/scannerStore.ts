import { create } from "zustand";
import { scannerApi } from "@/api/client";
import type { RankedSpread, ScannerFilters, ScannerResult } from "@/types";
import { DEFAULT_FILTERS } from "@/types";

const POLL_INTERVAL_MS = 3000;

interface ScannerStore {
  filters: ScannerFilters;
  result: ScannerResult | null;
  isLoading: boolean;
  error: string | null;
  selectedSpread: RankedSpread | null;
  lastScanDuration: number | null;

  setFilters: (partial: Partial<ScannerFilters>) => void;
  resetFilters: () => void;
  runScan: () => Promise<void>;
  selectSpread: (spread: RankedSpread | null) => void;
  clearResults: () => void;
}

export const useScannerStore = create<ScannerStore>((set, get) => ({
  filters: { ...DEFAULT_FILTERS },
  result: null,
  isLoading: false,
  error: null,
  selectedSpread: null,
  lastScanDuration: null,

  setFilters: (partial) =>
    set((state) => ({ filters: { ...state.filters, ...partial } })),

  resetFilters: () => set({ filters: { ...DEFAULT_FILTERS } }),

  runScan: async () => {
    set({ isLoading: true, error: null, selectedSpread: null });
    try {
      // Start the scan — returns immediately with a scan_id
      const job = await scannerApi.startScan(get().filters);

      // Poll until complete or failed
      await new Promise<void>((resolve, reject) => {
        const poll = async () => {
          try {
            const status = await scannerApi.getScanStatus(job.scan_id);
            if (status.status === "complete" && status.result) {
              set({
                result: status.result,
                isLoading: false,
                lastScanDuration: status.result.scan_duration_seconds,
              });
              resolve();
            } else if (status.status === "failed") {
              reject(new Error(status.error || "Scan failed"));
            } else {
              setTimeout(poll, POLL_INTERVAL_MS);
            }
          } catch (err) {
            reject(err);
          }
        };
        setTimeout(poll, POLL_INTERVAL_MS);
      });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : String(err),
        isLoading: false,
      });
    }
  },

  selectSpread: (spread) => set({ selectedSpread: spread }),
  clearResults: () =>
    set({ result: null, selectedSpread: null, error: null }),
}));
