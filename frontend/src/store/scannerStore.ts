import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { scannerApi } from "@/api/client";
import type { RankedSpread, ScannerFilters, ScannerResult } from "@/types";
import { DEFAULT_FILTERS } from "@/types";

const POLL_INTERVAL_MS = 3000;

// ─── Results-table columns ────────────────────────────────────────────────────
// Canonical column order (superset). The first block is visible by default; the
// rest are opt-in via the column picker. Column *definitions* live in ResultsTable
// keyed by these same ids — this file only owns the order/visibility so it can be
// persisted. Ids are append-only; renaming one just drops it from a saved layout
// (reconcileOrder handles it), never corrupts the table.
export const DEFAULT_COLUMN_ORDER: string[] = [
  "rank", "ticker", "strategy", "fit", "expiry", "dte", "iv_rank", "pop",
  "ml_score", "risk_score", "net_debit", "max_profit", "earnings",
  // opt-in extras (hidden by default)
  "breakeven", "spread_width", "max_loss", "bid_ask_quality", "expected_return",
  "confidence", "fundamental", "sentiment", "delta", "oi", "volume", "sector",
];

const DEFAULT_VISIBLE_COLUMNS = new Set([
  "rank", "ticker", "strategy", "fit", "expiry", "dte", "iv_rank", "pop",
  "ml_score", "risk_score", "net_debit", "max_profit", "earnings",
]);

export const DEFAULT_COLUMN_VISIBILITY: Record<string, boolean> = Object.fromEntries(
  DEFAULT_COLUMN_ORDER.map((id) => [id, DEFAULT_VISIBLE_COLUMNS.has(id)])
);

// Detail-panel cards, in default stacking order. Ids match the registry in ScannerPage.
export const DEFAULT_CARD_ORDER: string[] = [
  "spread", "ml", "sentiment", "risk", "fundamentals",
];

/** Keep only known ids (in persisted order), then append any defaults that are
 *  missing — so a stale/renamed layout can never drop or duplicate a column/card. */
function reconcileOrder(persisted: unknown, defaults: string[]): string[] {
  const allowed = new Set(defaults);
  const out: string[] = [];
  const seen = new Set<string>();
  if (Array.isArray(persisted)) {
    for (const id of persisted) {
      if (typeof id === "string" && allowed.has(id) && !seen.has(id)) {
        out.push(id);
        seen.add(id);
      }
    }
  }
  for (const id of defaults) if (!seen.has(id)) out.push(id);
  return out;
}

function reconcileVisibility(
  persisted: unknown,
  defaults: Record<string, boolean>
): Record<string, boolean> {
  const p = persisted && typeof persisted === "object" ? (persisted as Record<string, unknown>) : {};
  const out: Record<string, boolean> = {};
  for (const id of Object.keys(defaults)) {
    out[id] = typeof p[id] === "boolean" ? (p[id] as boolean) : defaults[id];
  }
  return out;
}

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

  /** Results-table layout — persisted */
  columnOrder: string[];
  columnVisibility: Record<string, boolean>;
  /** Detail-card stacking order — persisted */
  cardOrder: string[];

  setColumnOrder: (order: string[]) => void;
  setColumnVisibility: (visibility: Record<string, boolean>) => void;
  resetColumns: () => void;
  setCardOrder: (order: string[]) => void;

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
        columnOrder: [...DEFAULT_COLUMN_ORDER],
        columnVisibility: { ...DEFAULT_COLUMN_VISIBILITY },
        cardOrder: [...DEFAULT_CARD_ORDER],

        setColumnOrder: (order) => set({ columnOrder: order }),
        setColumnVisibility: (visibility) => set({ columnVisibility: visibility }),
        resetColumns: () =>
          set({
            columnOrder: [...DEFAULT_COLUMN_ORDER],
            columnVisibility: { ...DEFAULT_COLUMN_VISIBILITY },
          }),
        setCardOrder: (order) => set({ cardOrder: order }),

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
      version: 2,
      storage: createJSONStorage(() => localStorage),
      // Persist only small, durable state — never results or loading flags.
      partialize: (state) => ({
        filters: state.filters,
        activeScanId: state.activeScanId,
        presets: state.presets,
        columnOrder: state.columnOrder,
        columnVisibility: state.columnVisibility,
        cardOrder: state.cardOrder,
      }),
      // No-op migrate: the v1 shape is a strict subset of v2, so pass it straight
      // to merge (which backfills the new keys). This just suppresses the "no
      // migrate function" console error on the first v1→v2 rehydrate.
      migrate: (persisted) => persisted as Partial<ScannerStore>,
      // Merge persisted state over defaults so newly added fields get their
      // defaults, and reconcile column/card ids so a stale layout can't corrupt.
      merge: (persisted, current) => {
        const p = (persisted ?? {}) as Partial<ScannerStore>;
        return {
          ...current,
          ...p,
          filters: { ...DEFAULT_FILTERS, ...(p.filters ?? {}) },
          presets: p.presets ?? {},
          columnOrder: reconcileOrder(p.columnOrder, DEFAULT_COLUMN_ORDER),
          columnVisibility: reconcileVisibility(p.columnVisibility, DEFAULT_COLUMN_VISIBILITY),
          cardOrder: reconcileOrder(p.cardOrder, DEFAULT_CARD_ORDER),
        };
      },
    }
  )
);
