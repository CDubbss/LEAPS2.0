import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
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
  /** scan_id of an in-flight scan — persisted so a refresh can reattach */
  activeScanId: string | null;
  /** Saved filter presets by name — persisted */
  presets: Record<string, ScannerFilters>;

  setFilters: (partial: Partial<ScannerFilters>) => void;
  resetFilters: () => void;
  runScan: () => Promise<void>;
  /** Reattach to a scan that was running when the page was last closed. */
  resumeActiveScan: () => Promise<void>;
  selectSpread: (spread: RankedSpread | null) => void;
  clearResults: () => void;
  savePreset: (name: string) => void;
  applyPreset: (name: string) => void;
  deletePreset: (name: string) => void;
  /** Pull server-side presets and merge them in (server wins). */
  loadPresets: () => Promise<void>;
}

export const useScannerStore = create<ScannerStore>()(
  persist(
    (set, get) => {
      /** Poll a scan until it reaches a terminal state; updates store. */
      const pollUntilDone = (scanId: string) =>
        new Promise<void>((resolve, reject) => {
          const poll = async () => {
            try {
              const status = await scannerApi.getScanStatus(scanId);
              if (status.status === "complete" && status.result) {
                set({
                  result: status.result,
                  isLoading: false,
                  activeScanId: null,
                  lastScanDuration: status.result.scan_duration_seconds,
                });
                resolve();
              } else if (status.status === "failed") {
                set({ activeScanId: null });
                reject(new Error(status.error || "Scan failed"));
              } else {
                setTimeout(poll, POLL_INTERVAL_MS);
              }
            } catch (err) {
              set({ activeScanId: null });
              reject(err);
            }
          };
          setTimeout(poll, POLL_INTERVAL_MS);
        });

      return {
        filters: { ...DEFAULT_FILTERS },
        result: null,
        isLoading: false,
        error: null,
        selectedSpread: null,
        lastScanDuration: null,
        activeScanId: null,
        presets: {},

        setFilters: (partial) =>
          set((state) => ({ filters: { ...state.filters, ...partial } })),

        resetFilters: () => set({ filters: { ...DEFAULT_FILTERS } }),

        runScan: async () => {
          set({ isLoading: true, error: null, selectedSpread: null });
          try {
            const job = await scannerApi.startScan(get().filters);
            set({ activeScanId: job.scan_id });
            await pollUntilDone(job.scan_id);
          } catch (err) {
            set({
              error: err instanceof Error ? err.message : String(err),
              isLoading: false,
            });
          }
        },

        resumeActiveScan: async () => {
          const scanId = get().activeScanId;
          if (!scanId || get().isLoading) return;
          set({ isLoading: true, error: null });
          try {
            // One immediate check: complete → load result; running → keep polling.
            const status = await scannerApi.getScanStatus(scanId);
            if (status.status === "complete" && status.result) {
              set({
                result: status.result,
                isLoading: false,
                activeScanId: null,
                lastScanDuration: status.result.scan_duration_seconds,
              });
            } else if (status.status === "running") {
              await pollUntilDone(scanId);
            } else {
              set({ isLoading: false, activeScanId: null });
            }
          } catch {
            // Scan id no longer known to the backend (restart) — drop it silently.
            set({ isLoading: false, activeScanId: null });
          }
        },

        selectSpread: (spread) => set({ selectedSpread: spread }),
        clearResults: () =>
          set({ result: null, selectedSpread: null, error: null }),

        savePreset: (name) => {
          const filters = { ...get().filters };
          set((state) => ({
            presets: { ...state.presets, [name]: filters },
          }));
          // Server is the durable store; localStorage is just a warm cache.
          scannerApi.savePreset(name, filters).catch((e) => {
            console.warn("Preset saved locally but server sync failed:", e);
          });
        },

        applyPreset: (name) => {
          const preset = get().presets[name];
          if (preset) {
            // Merge over defaults so presets saved before new filter fields
            // existed still produce a complete ScannerFilters object.
            set({ filters: { ...DEFAULT_FILTERS, ...preset } });
          }
        },

        deletePreset: (name) => {
          set((state) => {
            const presets = { ...state.presets };
            delete presets[name];
            return { presets };
          });
          scannerApi.deletePreset(name).catch((e) => {
            console.warn("Preset deleted locally but server sync failed:", e);
          });
        },

        loadPresets: async () => {
          try {
            const server = await scannerApi.getPresets();
            set((state) => ({ presets: { ...state.presets, ...server } }));
          } catch (e) {
            console.warn("Could not load server presets:", e);
          }
        },
      };
    },
    {
      name: "leaps-scanner",
      version: 1,
      storage: createJSONStorage(() => localStorage),
      // Persist only small, durable state — never results or loading flags.
      partialize: (state) => ({
        filters: state.filters,
        activeScanId: state.activeScanId,
        presets: state.presets,
      }),
      // Merge persisted filters over defaults so newly added filter fields
      // get their default values instead of being undefined.
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<ScannerStore>;
        return {
          ...current,
          ...p,
          filters: { ...DEFAULT_FILTERS, ...(p.filters ?? {}) },
          presets: p.presets ?? {},
        };
      },
    }
  )
);
