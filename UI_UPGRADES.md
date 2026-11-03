# Leaps2.0 — UI functional upgrades (proposed)

> Author's note (to myself and to any agent picking this up): this is a **prioritized,
> implementation-ready backlog**, not a wish list. Each item is tied to a stated project
> goal (HANDOFF §1) and to what the model is *actually validated* to do (HANDOFF §10), so
> we don't build UI that oversells the model. Ranked by (goal alignment × leverage ÷ effort).
> Drafted 2026-10-20 alongside the health-pass fixes on branch `fix/health-20261020`.

## Guardrails that bind every item
- **No automated trading, ever.** The UI surfaces signals and enforces *discipline*; a human places every order. Any "sell/exit" control is a reminder, not an action.
- **Scores are ordinal within one model era only** (HANDOFF §10). Never render a raw score as if it were a probability or compare scores across model versions.
- **Logged P&L is pessimistic** (worst-case entry fill, §4.4). Label it as such wherever shown.
- **Security first** (CLAUDE.md §5): no new unauthenticated endpoints; notifications are local/browser-only; nothing leaves the box. Respect the existing BasicAuth when `REVIEW_PASSWORD` is set.

---

## Priority ranking

| # | Upgrade | Goal served | Leverage | Effort | New backend? |
|---|---|---|---|---|---|
| 1 | Exit-discipline command center (/positions) | #1 Don't lose to indiscipline | High | M | small |
| 2 | "Top N%" percentile badge (scanner) | #2 Find the top slice | High | S–M | none |
| 3 | Fundamentals freshness / as-of chip | #3 Honest track record | Med | S | small |
| 4 | EV + position-sizing helper | Risk framing (CLAUDE.md) | Med | M | none |
| 5 | Per-position price-path sparkline | Interprets §4.4 pessimism | Med | M | small |
| 6 | Scanner score "why" breakdown | Trust / explainability | Low–Med | S | none |

---

### 1. Exit-discipline command center — `/positions`
**Why:** Goal #1 is mechanical exit enforcement. Today the ±50% / EXIT-BY badges render per row *on demand*. The highest-leverage UI change is making un-acted exits impossible to miss.

**Build:**
- A sticky summary banner: counts of positions `TARGET HIT`, `STOP HIT`, `EXIT BY ≤ 2 days`, `EXPIRED?`. Clicking a count filters the table.
- Optional **browser notifications** (`Notification` API, opt-in, permission-gated) fired when a *refreshed* position crosses a threshold. Local only — no push server.
- A one-click "mark reviewed / acknowledged" per alert so the banner reflects decisions, not just state.

**Acceptance:** With a seeded position past +50%, the banner shows `1 TARGET HIT`, and (if the user opted in) a browser notification fires on the next price refresh. No network egress beyond the existing yfinance price call.

**Risks/notes:** Keep it a *reminder*. No "sell" button that does anything but open the broker in a new tab. Don't poll aggressively — reuse the existing on-demand refresh cadence to respect yfinance limits.

---

### 2. "Top N%" percentile badge — scanner results (`ResultsTable.tsx`)
**Why:** The one validated ranking fact is that signal lives in the **top decile** (HANDOFF §10). A raw score of 61 means nothing to the eye; "Top 5%" means exactly the thing that's validated.

**Build:**
- Compute the percentile of each result's `ml_score` **within the current scan's result set** (same model era by construction — sidesteps the §4.1 era-pooling trap with zero new data).
- Badge the top 5% / 10% (`TOP 5%`, `TOP 10%`); leave the rest unbadged rather than implying a smooth ranking below the top slice.
- Tooltip: "Percentile within this scan's candidates for the current model version. The model's edge is concentrated here (see validation)."

**Acceptance:** Badges reproduce a manual percentile computation on the result list; no score is compared across scans/eras.

**Risks/notes:** Do **not** compute percentile from a pooled historical distribution unless it's segmented by `model_version` (that's the deferred §4.1/E backend work). Within-scan percentile is the safe, shippable version now.

---

### 3. Fundamentals freshness / as-of chip
**Why:** Today's §4.9 fix adds an intentional **last-good fallback** — a shown PE may now be up to 90 days stale on FMP outages. Honesty (goal #3) requires surfacing that.

**Build:**
- Add a `fetched_at` (and optional `is_stale`) timestamp to `FundamentalData` and the scan result payload; stamp it where fundamentals are fetched/served.
- Render an "as of <date>" chip in the ticker modal / detail card; amber chip when older than e.g. 14 days.

**Acceptance:** A symbol served from the last-good cache shows its true as-of date, not "now".

---

### 4. EV + position-sizing helper
**Why:** CLAUDE.md §5 wants downside and risk made explicit. The classifier gives P(hit +50% before −50%); with the symmetric ±50% payoff and commissions (HANDOFF §1) that's a one-line EV.

**Build:**
- Per candidate: `EV_per_$risked = p·0.5 − (1−p)·0.5 − commission_drag`, shown next to the badge (clearly "model-implied, in-sample — not a guarantee").
- A sizing panel: user enters bankroll + max risk %; show suggested max contracts given net debit and the backtest **max drawdown** ($64k, HANDOFF §3) as the survivability anchor.

**Risks/notes:** Label loudly as mechanical arithmetic on an in-sample probability, **not** advice (CLAUDE.md §9 / prohibited personalized financial advice). No bankroll value is persisted server-side.

---

### 5. Per-position price-path sparkline
**Why:** §4.4 — positions start "underwater" by the full bid-ask cross, which confuses the P&L reading. Showing the mid-to-mid path makes the entry-pessimism legible.

**Build:** a `GET` endpoint returning a position's `price_snapshots` series (read-only, from the outcomes DB — mind the lock contention note §6; consider the presets-DB pattern or a short cache); render a sparkline with entry-worst-case vs mid-to-mid markers.

---

### 6. Scanner score "why" breakdown
**Why:** The 5-factor composite risk score is already computed (`iv_rank·0.25 + bid_ask·0.20 + fundamental·0.25 + sentiment·0.15 + liquidity·0.15`). Surfacing the breakdown in the detail card is cheap trust-building.

**Build:** a small stacked-bar / factor list in `SpreadDetailCard.tsx` from fields already in the payload. No backend change if the sub-scores are already serialized; otherwise add them to the result model.

---

## Suggested sequencing for an implementing agent
1. **#2 percentile badge** first — pure frontend, zero data risk, immediate daily value, proves the "top-slice" framing in the UI.
2. **#1 exit command center** — the highest-goal-aligned change; small backend (acknowledge state) + notifications.
3. **#3 freshness chip** — closes the loop on today's §4.9 fundamentals fix.
4. Then #4 / #6 (frontend-weighted), #5 last (needs a snapshots endpoint + lock care).

Each is independently shippable; none requires the deferred era-segmentation backend (§4.1/E) **except** a *historical* pooled percentile, which is deliberately excluded from #2.
