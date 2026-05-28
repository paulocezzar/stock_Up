# Business Performance Design System

This reference documents the visual language already established by the Business Performance dashboard. Reuse these exact Tailwind class patterns when restyling Django templates or React components. Do not introduce new colour roles or component styles unless the Business Performance surface is updated first.

## Page Shell

- App shell:
  - `min-h-screen bg-[#f5f7fb] text-slate-950 dark:bg-slate-950 dark:text-slate-100`
- Sidebar offset:
  - `ml-64 min-w-0`
- Main page container:
  - `mx-auto w-full max-w-[1760px] px-8 py-7`
- Main content wrapper:
  - `w-full`
- Standard grid gaps:
  - `gap-5`
  - vertical row spacing uses `mt-5`
- Desktop dashboard grids:
  - KPI grid: `grid w-full grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4`
  - Paired 8/4 rows: `hidden gap-5 xl:grid xl:grid-cols-12 xl:items-stretch`
  - 8-column cell: `col-span-8 min-w-0`
  - 4-column cell: `col-span-4 min-w-0`

## Cards And Sections

- Standard card:
  - `w-full rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900`
- Standard card with asymmetric padding:
  - `w-full rounded-xl border border-slate-200 bg-white px-5 pb-2.5 pt-5 shadow-sm dark:border-slate-800 dark:bg-slate-900`
- Muted insight card:
  - `w-full rounded-xl border border-slate-200 bg-slate-50/70 p-5 dark:border-slate-800 dark:bg-slate-900/60`
- Compact strip card:
  - `mt-5 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-900`
- Inner framed surface:
  - `rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/50`
- Empty/dashed state:
  - `rounded-lg border border-dashed border-slate-200 px-3 py-4 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400`

## Typography

- Page uses Space Grotesk by default through `body`; mono/tabular values use `.tabular`.
- Card heading:
  - `font-display text-base font-semibold text-slate-950 dark:text-slate-100`
- KPI value:
  - `mt-2 break-words font-display text-2xl font-semibold tracking-normal text-slate-950 dark:text-slate-100`
- Small label:
  - `text-xs font-medium text-slate-500 dark:text-slate-400`
- Muted subtext:
  - `mt-1 text-xs text-slate-500 dark:text-slate-400`
  - alternate: `mt-1 text-xs text-slate-600 dark:text-slate-300`
- Table text:
  - `text-sm`
  - table header text: `text-xs font-semibold text-slate-500 dark:text-slate-400`
- Numeric/tabular cells:
  - `tabular`
  - strong numeric value: `tabular font-semibold text-slate-950 dark:text-slate-100`
  - muted numeric value: `tabular text-slate-500 dark:text-slate-400`

## Colour Roles

- Page neutral:
  - light background `bg-[#f5f7fb]`
  - dark background `dark:bg-slate-950`
  - card background `bg-white dark:bg-slate-900`
  - muted surface `bg-slate-50/70 dark:bg-slate-900/60`
  - deepest inner surface `dark:bg-slate-950/50`
- Borders:
  - `border-slate-200 dark:border-slate-800`
  - lighter table row border: `border-slate-100 dark:border-slate-800`
- Text:
  - primary `text-slate-950 dark:text-slate-100`
  - secondary `text-slate-700 dark:text-slate-300`
  - muted `text-slate-500 dark:text-slate-400`
  - tertiary `text-slate-400 dark:text-slate-500`
- Amber accent:
  - icon surface: `bg-amber-50 text-amber-700 dark:bg-amber-400/15 dark:text-amber-200`
  - active segmented channel: `bg-amber-100 text-amber-900 dark:bg-amber-400/15 dark:text-amber-200`
  - warning pill: `border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200`
  - progress/heat accent: `bg-amber-500`
- Positive:
  - `bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300`
  - `border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300`
- Negative:
  - `bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300`
  - `border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300`
- Series colours:
  - wholesale line `#6d28d9`, class `bg-wholesale`
  - internal line `#0284c7`, class `bg-internal`

## Components

### KPI Tile

- Root:
  - `w-full rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900`
- Header layout:
  - `flex items-start justify-between gap-4`
- Icon box:
  - `flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-700 dark:bg-amber-400/15 dark:text-amber-200`
- Footer line:
  - `mt-4 flex min-h-6 items-center justify-between gap-3`

### Chip

- Compact chip:
  - `rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 dark:border-slate-800 dark:bg-slate-950/60`
- Insight chip:
  - `rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-950/50 dark:text-slate-300`

### Pills And Badges

- State badge, neutral:
  - `border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300`
- State badge, declined/negative:
  - `border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300`
- Concentration badge:
  - `shrink-0 rounded-md border px-2 py-1 text-xs font-semibold`
- 80/20 pill:
  - `ml-2 inline-block rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 align-middle text-[10px] font-semibold text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200`

### Segmented Toggles

- Wrapper:
  - `inline-flex h-10 items-center rounded-lg border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900`
- Button base:
  - `h-8 rounded-md px-3 text-sm font-medium transition`
- Neutral active:
  - `bg-slate-200 text-slate-950 shadow-sm dark:bg-slate-700 dark:text-white`
- Amber active:
  - `bg-amber-100 text-amber-900 dark:bg-amber-400/15 dark:text-amber-200`
- Inactive:
  - `text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white`

### Select Controls

- Select wrapper:
  - `relative inline-flex h-10 items-center rounded-lg border border-slate-200 bg-white px-3 shadow-sm dark:border-slate-800 dark:bg-slate-900`
- Select element:
  - `h-8 appearance-none bg-transparent pr-7 text-sm font-medium text-slate-700 outline-none dark:text-slate-300`
- Chevron:
  - `pointer-events-none absolute right-3 text-slate-400`

### Buttons

- Secondary/export button:
  - `inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:text-white`
- Small utility button:
  - `rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-800 dark:hover:text-white`
- Icon-only utility button:
  - `inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-400 dark:hover:bg-slate-800`
- Expander button:
  - `mt-3 inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-800 dark:hover:text-white`

### Delta Pill

- Base:
  - `inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold tabular`
- Positive:
  - `border-emerald-200 bg-emerald-50 text-emerald-700`
- Negative:
  - `border-rose-200 bg-rose-50 text-rose-700`

### Tables

- Table:
  - `w-full text-sm`
  - heatmap uses `w-full table-fixed text-xs`
- Table header row:
  - `border-b border-slate-200 text-left text-xs font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400`
  - heatmap header uses `border-b border-slate-100 text-left font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400`
- Row:
  - `border-b border-slate-100 transition-colors last:border-0 hover:bg-slate-50/80 dark:border-slate-800 dark:hover:bg-slate-800/50`
- Standard padding:
  - `py-2.5 px-2`
  - first numeric rank cell: `w-8 py-2.5 pr-2 text-right`
- Links/names should use:
  - `font-medium text-slate-800 dark:text-slate-200`
  - avoid amber for ordinary table links.

### Heatmap Cells

- Cell:
  - `flex h-6 w-full items-center justify-center rounded tabular text-[10px] font-semibold text-slate-950 ring-1 ring-inset ring-amber-900/5 dark:text-slate-100 sm:text-[11px]`
- Empty cells use a muted background and transparent text via inline style:
  - `background: rgba(148, 163, 184, 0.08)`
- Positive heat uses amber:
  - `rgba(245, 164, 0, alpha)`
