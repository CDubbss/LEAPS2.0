import { create } from "zustand";
import { scannerApi } from "@/api/client";
import type { RankedSpread, ScannerFilters, ScannerResult } from "@/types";
import { DEFAULT_FILTERS } from "@/types";

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
      const result = await scannerApi.runScan(get().filters);
      set({
        result,
        isLoading: false,
        lastScanDuration: result.scan_duration_seconds,
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
