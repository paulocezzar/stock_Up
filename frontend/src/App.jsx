import { useCallback, useEffect, useState } from "react";
import {
  PoundSterling,
  PieChart as PieIcon,
  ShoppingBag,
  Leaf,
  ArrowLeftRight,
  Filter,
  Lock,
} from "lucide-react";
import Sidebar from "./components/Sidebar.jsx";
import MetricCard from "./components/MetricCard.jsx";
import WeekPicker from "./components/WeekPicker.jsx";
import DailyTrendChart from "./components/DailyTrendChart.jsx";
import ChannelSplitDonut from "./components/ChannelSplitDonut.jsx";
import InsightsPanel from "./components/InsightsPanel.jsx";
import TopCustomersTable from "./components/TopCustomersTable.jsx";
import ProductDayMatrix from "./components/ProductDayMatrix.jsx";
import ProductionLoadPlaceholder from "./components/ProductionLoadPlaceholder.jsx";
import ChannelBreakdownPlaceholder from "./components/ChannelBreakdownPlaceholder.jsx";
import QuickActions from "./components/QuickActions.jsx";
import RecentOrders from "./components/RecentOrders.jsx";
import WeeklySummary from "./components/WeeklySummary.jsx";
import { fetchWeekSummary, exportCsvUrl } from "./lib/api.js";
import { gbp, pct, weekLongLabel } from "./lib/format.js";

// Single-week dashboard, fixed left rail (Sidebar w-64) + main content
// with max-w-[1900px] mx-auto p-6. One API call per selected week, no
// client-side aggregation.
export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null); // null = "latest"

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchWeekSummary(selected || undefined)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        if (selected === null) setSelected(d.week_start);
      })
      .catch((e) => !cancelled && setError(e.message || String(e)));
    return () => { cancelled = true; };
  }, [selected]);

  const onCompare = useCallback(() => {
    if (data?.prev_week_start) setSelected(data.prev_week_start);
  }, [data]);

  return (
    <div className="flex min-h-screen bg-page text-slate-100">
      <Sidebar />
      <main className="min-w-0 flex-1 p-6">
        <div className="max-w-[1900px] mx-auto">
          <Header
            data={data}
            selected={selected}
            onSelect={setSelected}
            onCompare={onCompare}
          />
          {error && (
            <div className="rounded-2xl border border-neg/40 bg-neg/10 p-4 text-rose-200">
              Failed to load dashboard: {error}
            </div>
          )}
          {!data && !error && (
            <div className="font-mono text-xs uppercase tracking-widest text-slate-500">
              Loading…
            </div>
          )}
          {data && <Body data={data} onCompare={onCompare} />}
          {data && <Footer weekStart={data.week_start} />}
        </div>
      </main>
    </div>
  );
}

function Header({ data, selected, onSelect, onCompare }) {
  const hasPrev = Boolean(data?.prev_week_start);
  return (
    <header className="mb-6 flex flex-wrap items-center justify-between gap-4">
      <div>
        <div className="flex items-center gap-2.5">
          <h1 className="font-display text-3xl font-bold tracking-tight text-slate-100">
            Overview
          </h1>
          <span className="relative inline-flex h-2.5 w-2.5" title="Live data">
            <span className="absolute inline-flex h-full w-full rounded-full bg-brand opacity-75 animate-ping" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-brand" />
          </span>
        </div>
        <p className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-1.5">
          {data
            ? `Performance overview for w/c ${weekLongLabel(data.week_start)}`
            : "Performance overview"}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {data && (
          <WeekPicker
            value={selected || data.week_start}
            options={data.available_weeks}
            onChange={onSelect}
          />
        )}
        {data?.prev_week_start && (
          <span
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-800 bg-card/60 text-xs font-mono text-slate-400"
            title="Previous imported week, used as the comparison baseline"
          >
            <span className="text-slate-600 uppercase tracking-widest text-[10px]">vs</span>
            w/c {weekLongLabel(data.prev_week_start)}
          </span>
        )}
        <button
          type="button"
          onClick={onCompare}
          disabled={!hasPrev}
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-800 bg-card hover:border-brand/40 transition text-xs text-slate-200 font-display disabled:opacity-40 disabled:cursor-not-allowed"
          title={hasPrev ? `Compare to w/c ${data.prev_week_start}` : "No prior week"}
        >
          <ArrowLeftRight size={14} strokeWidth={1.75} />
          Compare
        </button>
        <button
          type="button"
          disabled
          className="inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-800/60 bg-card/60 text-xs text-slate-500 font-display cursor-not-allowed"
          title="Filters need backend support — coming soon"
        >
          <Filter size={14} strokeWidth={1.75} />
          Filters
          <Lock size={10} strokeWidth={2} className="ml-0.5 text-slate-600" />
        </button>
      </div>
    </header>
  );
}

function Body({ data, onCompare }) {
  return (
    <>
      {/* Row 1: KPIs — six equal cards, full width */}
      <Kpis data={data} />

      {/* Below KPIs: LEFT/CENTER region | RIGHT RAIL (fixed 320px).
          The right rail stacks Insights → Quick Actions → Weekly
          Summary. The left/center region runs its own internal rows
          A (chart + donut), B (3-up customers + 2 placeholders), C
          (Recent Orders). */}
      <div className="mt-4 grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_320px] gap-4">
        <div className="space-y-4 min-w-0">
          {/* Row A: Daily Trend (2fr) | Channel Split (1fr) */}
          <div className="grid grid-cols-1 lg:grid-cols-[2fr_1fr] gap-4">
            <DailyTrendChart rows={data.daily_trend} hasPrev={Boolean(data.prev_week_start)} />
            <ChannelSplitDonut internal={data.internal} wholesale={data.wholesale} />
          </div>
          {/* Row B: 3-up — Top Wholesale | Production Load (placeholder) | Channel Breakdown (placeholder) */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <TopCustomersTable rows={data.top_wholesale} />
            <ProductionLoadPlaceholder />
            <ChannelBreakdownPlaceholder />
          </div>
          {/* Row C: Recent Orders, full width of left/center */}
          <div>
            <RecentOrders rows={data.recent_orders} />
          </div>
        </div>
        <aside className="space-y-4">
          <InsightsPanel
            total_ordered={data.total_ordered}
            wow={data.wow}
            internal={data.internal}
            wholesale={data.wholesale}
            top_wholesale={data.top_wholesale}
            top_internal={data.top_internal}
            highest_day={data.highest_day}
            lowest_day={data.lowest_day}
          />
          <QuickActions
            exportHref={exportCsvUrl(data.week_start)}
            prevWeek={data.prev_week_start}
            onCompare={onCompare}
          />
          <WeeklySummary
            highest_day={data.highest_day}
            lowest_day={data.lowest_day}
            top_wholesale={data.top_wholesale}
            top_internal={data.top_internal}
            internal={data.internal}
            wholesale={data.wholesale}
          />
        </aside>
      </div>

      {/* Below everything: Product × Day, full width (real data) */}
      <div className="mt-4">
        <ProductDayMatrix rows={data.product_day_matrix} />
      </div>
    </>
  );
}

function Footer({ weekStart }) {
  return (
    <footer className="mt-8 pt-4 border-t border-slate-800 flex flex-wrap items-center justify-between gap-2 font-mono text-[10px] uppercase tracking-widest text-slate-600">
      <span>All figures for w/c {weekLongLabel(weekStart)}</span>
      <span>Ordered value · excl. VAT</span>
    </footer>
  );
}

function Kpis({ data }) {
  // Real WoW % only on Total Ordered + Avg Daily Ordered. Avg Daily
  // shares the same WoW because avg-per-day scales linearly with the
  // week's total — both reduce to wow.pct. Channel-share cards
  // (Wholesale %, Internal %) and Total Orders / Waste % have no
  // honest WoW data exposed by the API, so they omit the delta (the
  // line collapses to just the static subline).
  const wowPct = data.wow?.pct;
  const daily = (data.daily_trend || []).map((r) => Number(r.total));
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <MetricCard
        label="Total Ordered"
        value={gbp(data.total_ordered)}
        delta={wowPct ?? undefined}
        deltaSubline={wowPct === null || wowPct === undefined ? "No prior week" : undefined}
        icon={PoundSterling}
        accent="brand"
        sparkline={daily}
        hint="Sum of qty × unit_price across all external order lines this week."
      />
      <MetricCard
        label="Wholesale %"
        value={pct(data.wholesale?.pct)}
        deltaSubline={gbp(data.wholesale?.total)}
        icon={PieIcon}
        accent="wholesale"
        deltaSuffix="pp"
        hint="Wholesale-channel share of external ordered value."
      />
      <MetricCard
        label="Internal %"
        value={pct(data.internal?.pct)}
        deltaSubline={gbp(data.internal?.total)}
        icon={PieIcon}
        accent="internal"
        deltaSuffix="pp"
        hint="Internal-channel share (all external customers NOT wholesale)."
      />
      <MetricCard
        label="Total Orders"
        value={data.total_orders ?? "—"}
        deltaSubline="Order lines this week"
        icon={ShoppingBag}
        accent="internal"
        hint="Count of external order lines (not distinct orders)."
      />
      <MetricCard
        label="Waste %"
        value="Not tracked"
        deltaSubline="Needs setup (Chunk 4)"
        tone="neutral"
        icon={Leaf}
        accent="pos"
        hint="No waste data tracked yet — placeholder, not a real metric."
      />
      <MetricCard
        label="Avg Daily Ordered"
        value={gbp(data.avg_day)}
        delta={wowPct ?? undefined}
        deltaSubline={wowPct === null || wowPct === undefined ? "Total ÷ 7" : undefined}
        icon={PoundSterling}
        accent="brand"
        sparkline={daily}
        hint="Total ÷ 7 — moves with Total Ordered's WoW (linear scaling)."
      />
    </div>
  );
}
