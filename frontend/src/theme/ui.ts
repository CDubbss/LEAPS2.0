/**
 * Design tokens — single source of truth for all visual constants.
 *
 * HOW TO UPDATE THE GUI:
 *   • Change a value here → propagates to every component that imports it.
 *   • To swap accent color (sky → indigo): change all `sky-*` tokens below.
 *   • To adjust card density: change `card` padding token.
 *   • Components import individual tokens; nothing is hardcoded in JSX.
 */

// ---------------------------------------------------------------------------
// Surfaces & backgrounds
// ---------------------------------------------------------------------------
export const bg = {
  base:     'bg-gray-950',        // page background
  surface:  'bg-gray-900',        // sidebars, nav, sheets
  elevated: 'bg-gray-800',        // cards, dropdowns
  overlay:  'bg-black/60',        // modal backdrop
} as const;

// ---------------------------------------------------------------------------
// Borders
// ---------------------------------------------------------------------------
export const border = {
  default: 'border-gray-700',
  subtle:  'border-gray-800',
} as const;

// ---------------------------------------------------------------------------
// Text
// ---------------------------------------------------------------------------
export const text = {
  primary:   'text-white',
  secondary: 'text-gray-300',
  muted:     'text-gray-500',
  accent:    'text-sky-400',
  call:      'text-green-400',
  put:       'text-red-400',
  warning:   'text-orange-400',
} as const;

// ---------------------------------------------------------------------------
// Accent — buttons, active tabs, badges (swap these to rebrand)
// ---------------------------------------------------------------------------
export const accent = {
  bg:        'bg-sky-600',
  bgHover:   'hover:bg-sky-500',
  bgActive:  'bg-sky-700',
  text:      'text-sky-400',
  border:    'border-sky-500',
  ring:      'focus:ring-sky-500',
} as const;

// ---------------------------------------------------------------------------
// Interactive — secondary buttons, row hovers
// ---------------------------------------------------------------------------
export const interactive = {
  default: 'bg-gray-700 hover:bg-gray-600 transition-colors',
  subtle:  'hover:bg-gray-800/60 transition-colors',
} as const;

// ---------------------------------------------------------------------------
// Border radius
// ---------------------------------------------------------------------------
export const radius = {
  sm:   'rounded',
  md:   'rounded-lg',
  lg:   'rounded-xl',
  xl:   'rounded-2xl',
  full: 'rounded-full',
} as const;

// ---------------------------------------------------------------------------
// Spacing / sizing
// ---------------------------------------------------------------------------
export const size = {
  touchTarget:   'min-h-[44px]',   // WCAG / mobile touch minimum
  bottomBar:     'h-16',           // bottom tab bar height (64px)
  bottomBarPad:  'pb-16',          // content padding to clear bottom bar
  topNav:        'h-12',           // top nav height
  filterWidth:   'w-80',           // desktop filter sidebar
  detailWidth:   'w-96',           // desktop detail sidebar
} as const;

// ---------------------------------------------------------------------------
// Composite class strings — "shorthand" for common patterns
// ---------------------------------------------------------------------------

/** Standard card shell */
export const card =
  "bg-gray-800 rounded-xl border border-gray-700 p-3";

/** Bottom sheet container */
export const sheet =
  "bg-gray-900 rounded-t-2xl border-t border-gray-700";

/** Standard text input */
export const input =
  "bg-gray-800 border border-gray-600 text-white text-sm rounded-lg" +
  " px-3 py-2 focus:outline-none focus:border-sky-500";

/** Primary action button */
export const btnPrimary =
  "bg-sky-600 hover:bg-sky-500 text-white font-semibold rounded-lg" +
  " min-h-[44px] px-4 transition-colors";

/** Secondary action button */
export const btnSecondary =
  "bg-gray-700 hover:bg-gray-600 transition-colors text-gray-300 text-sm rounded-lg" +
  " min-h-[44px] px-4";

/** Active nav/tab pill */
export const navActive =
  `${accent.bgActive} ${text.primary}` as const;

/** Inactive nav/tab pill */
export const navInactive =
  "text-gray-500 hover:text-white hover:bg-gray-700";

/** Accordion section header */
export const accordionHeader =
  "flex items-center justify-between w-full px-4 py-3" +
  " text-sm font-medium text-gray-300 hover:bg-gray-800/60 transition-colors" +
  " border-b border-gray-700 select-none";
