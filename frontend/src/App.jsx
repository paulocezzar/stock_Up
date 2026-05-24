import { useEffect, useState } from "react";
import {
  PoundSterling,
  Store,
  Truck,
  CalendarRange,
  CalendarDays,
  Clock,
} from "lucide-react";
import Sidebar from "./components/Sidebar.jsx";
import MetricCard from "./components/MetricCard.jsx";
import WeeklyTrend from "./components/WeeklyTrend.jsx";
import { fetchDashboardSummary } from "./lib/api.js";
import { gbp, pct, weekLabel } from "./lib/format.js";

export default function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchDashboardSummary()
      .then(setData)
      .catch((e) => setError(e.message || String(e)));
  }, []);

  return (
    <div className="min-h-screen flex bg-ink text-slate-100">
      <Sidebar />
      <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8 overflow-x-hidden">
        <header className="mb-6 flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <h1 className="font-display text-2xl font-semibold tracking-tight">
              Dashboard
            </h1>
            <p className="font-mono text-[11px] uppercase tracking-widest text-slate-500 mt-1">
              Ordered demand · Internal + Wholesale · excludes bakery internal use
            </p>
          </div>
          {data && (
            <div className="font-mono text-[11px] uppercase tracking-widest text-slate-500">
              {weekLabel(data.from)} → {weekLabel(data.to)}
            </div>
          )}
        </header>

        {error && (
          <div className="rounded-md border border-rose-800 bg-rose-950/50 p-4 text-rose-200">
            Failed to load dashboard: {error}
          </div>
        )}

        {!data && !error && (
          <div className="font-mono text-xs uppercase tracking-widest text-slate-500">
            Loading…
          </div>
        )}

        {data && (
          <>
            <Kpis data={data} />
            <div className="mt-6">
              <WeeklyTrend rows={data.weekly_trend} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function Kpis({ data }) {
  const latest = data.latest_week;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      <MetricCard
        label="Total ordered"
        value={gbp(data.grand_total)}
        subline={`${weekLabel(data.from)} → ${weekLabel(data.to)}`}
        icon={PoundSterling}
      />
      <MetricCard
        label="Internal ordered"
        value={gbp(data.internal.total)}
        subline={`${pct(data.internal.pct)} of total`}
        icon={Store}
      />
      <MetricCard
        label="Wholesale ordered"
        value={gbp(data.wholesale.total)}
        subline={`${pct(data.wholesale.pct)} of total`}
        icon={Truck}
      />
      <MetricCard
        label="Avg per week"
        value={gbp(data.avg_week)}
        subline={`${data.weekly_trend.length} weeks in range`}
        icon={CalendarRange}
      />
      <MetricCard
        label="Avg per day"
        value={gbp(data.avg_day)}
        subline="Across selected range"
        icon={CalendarDays}
      />
      <MetricCard
        label="Latest week"
        value={latest ? gbp(latest.total) : "—"}
        subline={latest ? `w/c ${weekLabel(latest.week)}` : "No data"}
        delta={latest ? latest.wow_pct : undefined}
        icon={Clock}
      />
    </div>
  );
}
