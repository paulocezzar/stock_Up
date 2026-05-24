import { useCallback, useEffect, useState } from "react";
import {
  PoundSterling,
  Percent,
  ShoppingCart,
  Trash2,
  CalendarDays,
  Building2,
} from "lucide-react";
import Sidebar from "./components/Sidebar.jsx";
import MetricCard from "./components/MetricCard.jsx";
import WeekPicker from "./components/WeekPicker.jsx";
import DailyTrendChart from "./components/DailyTrendChart.jsx";
import ChannelSplitDonut from "./components/ChannelSplitDonut.jsx";
import InsightsPanel from "./components/InsightsPanel.jsx";
import TopCustomersTable from "./components/TopCustomersTable.jsx";
import ProductionHeatmap from "./components/ProductionHeatmap.jsx";
import QuickActions from "./components/QuickActions.jsx";
import RecentOrders from "./components/RecentOrders.jsx";
import WeeklySummary from "./components/WeeklySummary.jsx";
import { fetchWeekSummary, exportCsvUrl } from "./lib/api.js";
import { gbp, pct, weekLongLabel } from "./lib/format.js";

// Single-week dashboard. One API call per render, no client-side
// aggregation. Week picker re-fetches; "Compare Previous Week" is a
// shortcut that navigates the picker to data.prev_week_start.
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
        // First load: lock the selector to the week the server picked
        // so the URL of the dropdown matches what's shown.
        if (selected === null) setSelected(d.week_start);
      })
      .catch((e) => !cancelled && setError(e.message || String(e)));
    return () => { cancelled = true; };
  }, [selected]);

  const onCompare = useCallback(() => {
    if (data?.prev_week_start) setSelected(data.prev_week_start);
  }, [data]);

  return (
    <div className="min-h-screen flex bg-page text-slate-100">
      <Sidebar />
      <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8 overflow-x-hidden">
        <Header data={data} selected={selected} onSelect={setSelected} />
        {error && (
          <div className="rounded-xl border border-neg/40 bg-neg/10 p-4 text-rose-200">
            Failed to load dashboard: {error}
          </div>
        )}
        {!data && !error && (
          <div className="font-mono text-xs uppercase tracking-widest text-slate-500">
            Loading…
          </div>
        )}
        {data && <Body data={data} onCompare={onCompare} />}
      </main>
    </div>
  );
}

function Header({ data, selected, onSelect }) {
  return (
    <header className="mb-6 flex flex-wrap items-baseline justify-between gap-4">
      <div>
        <h1 className="font-display text-2xl font-semibold tracking-tight text-slate-100">
          Dashboard
        </h1>
        <p className="font-mono text-[11px] uppercase tracking-widest text-slate-500 mt-1">
          {data
            ? `Performance overview for w/c ${weekLongLabel(data.week_start)}`
            : "Performance overview"}
          {data?.prev_week_start && (
            <span className="ml-2 text-slate-600">
              vs w/c {weekLongLabel(data.prev_week_start)}
            </span>
          )}
        </p>
      </div>
      {data && (
        <WeekPicker
          value={selected || data.week_start}
          options={data.available_weeks}
          onChange={onSelect}
        />
      )}
    </header>
  );
}

function Body({ data, onCompare }) {
  return (
    <>
      <Kpis data={data} />
      <div className="mt-6 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <DailyTrendChart
            rows={data.daily_trend}
            hasPrev={Boolean(data.prev_week_start)}
          />
        </div>
        <ChannelSplitDonut internal={data.internal} wholesale={data.wholesale} />
      </div>
      <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
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
        </div>
        <WeeklySummary
          highest_day={data.highest_day}
          lowest_day={data.lowest_day}
          top_wholesale={data.top_wholesale}
          top_internal={data.top_internal}
          internal={data.internal}
          wholesale={data.wholesale}
        />
      </div>
      <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <TopCustomersTable rows={data.top_wholesale} />
        </div>
        <QuickActions
          exportHref={exportCsvUrl(data.week_start)}
          prevWeek={data.prev_week_start}
          onCompare={onCompare}
        />
      </div>
      <div className="mt-4 grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <RecentOrders rows={data.recent_orders} />
        </div>
        <ProductionHeatmap />
      </div>
    </>
  );
}

function Kpis({ data }) {
  // Real WoW pct, never fabricated. When prev_week is missing the
  // delta is omitted (the card collapses the delta row).
  const wowPct = data.wow?.pct;
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      <MetricCard
        label="Total Ordered"
        value={gbp(data.total_ordered)}
        delta={wowPct === undefined ? undefined : wowPct}
        subline={wowPct === null || wowPct === undefined
          ? "No prior week"
          : `vs ${gbp(data.wow.total)}`}
        icon={PoundSterling}
      />
      <MetricCard
        label="Wholesale %"
        value={pct(data.wholesale?.pct)}
        subline={gbp(data.wholesale?.total)}
        icon={Building2}
      />
      <MetricCard
        label="Internal %"
        value={pct(data.internal?.pct)}
        subline={gbp(data.internal?.total)}
        icon={Percent}
      />
      <MetricCard
        label="Total Orders"
        value={data.total_orders ?? "—"}
        subline="Order lines this week"
        icon={ShoppingCart}
      />
      <MetricCard
        label="Waste %"
        value="Not tracked"
        subline="Needs waste capture (Chunk 4)"
        tone="neutral"
        icon={Trash2}
      />
      <MetricCard
        label="Avg Daily Ordered"
        value={gbp(data.avg_day)}
        subline="Total ÷ 7"
        icon={CalendarDays}
      />
    </div>
  );
}
