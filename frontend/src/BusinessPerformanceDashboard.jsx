import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  AlertTriangle,
  BarChart3,
  PieChart as PieIcon,
  PoundSterling,
  ShieldAlert,
  Sparkles,
  TrendingUp,
  Users,
} from "lucide-react";
import Sidebar from "./components/Sidebar.jsx";
import BPWeeklyTrendChart from "./components/BPWeeklyTrendChart.jsx";
import BPCustomersTable from "./components/BPCustomersTable.jsx";
import BPProductPareto from "./components/BPProductPareto.jsx";
import { fetchBusinessPerformance } from "./lib/api.js";
import { gbp, pct, weekLongLabel } from "./lib/format.js";

// "Business Performance" is the multi-week commercial-finance lens —
// distinct from /dashboard/, which is single-week operational. This
// page is built around four questions:
//   1) Are we growing?           — Period Ordered + Δ, Run Rate
//   2) Where is the money?        — Channel Mix, Top customers
//   3) What's at risk?            — Concentration, Watchlist
//   4) Which products carry us?   — Pareto with 80/20 highlight
//
// All figures come from one API call (/api/business-performance/summary/).
// from/to is derived client-side from the selected period preset + the
// latest imported week; the server clamps if requested range extends
// before the earliest imported week.

const PERIOD_OPTIONS = [
  { key: "4w", label: "4w", weeks: 4 },
  { key: "8w", label: "8w", weeks: 8 },
  { key: "12w", label: "12w", weeks: 12 },
  { key: "26w", label: "26w", weeks: 26 },
  { key: "all", label: "All", weeks: null },
];

function dateMinusWeeks(iso, weeks) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - weeks * 7);
  return d.toISOString().slice(0, 10);
}

function computeFromTo(periodKey, earliest, latest) {
  if (!latest) return { from: undefined, to: undefined };
  const opt = PERIOD_OPTIONS.find((o) => o.key === periodKey) ?? PERIOD_OPTIONS[1];
  if (opt.weeks === null) return { from: earliest, to: latest };
  const from = dateMinusWeeks(latest, opt.weeks - 1);
  // The server clamps to earliest; client doesn't pre-clamp so the
  // request stays a single, predictable shape.
  return { from, to: latest };
}

export default function BusinessPerformanceDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [periodKey, setPeriodKey] = useState("8w");
  const [channel, setChannel] = useState("wholesale");

  // Initial fetch with no params — server returns its default 8-week
  // window. From then on, the period buttons drive from/to.
  const [request, setRequest] = useState({});

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchBusinessPerformance(request)
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => !cancelled && setError(e.message || String(e)));
    return () => { cancelled = true; };
  }, [request]);

  const selectPeriod = useCallback((key) => {
    if (key === periodKey) return;  // no-op on same-button re-click
    setPeriodKey(key);
    if (!data?.period) {
      // First load — let the server default decide. Just remember the
      // preference; the next render will refetch once latest_imported
      // arrives.
      return;
    }
    const next = computeFromTo(
      key, data.period.earliest_imported, data.period.latest_imported);
    setRequest(next);
  }, [data, periodKey]);

  return (
    <div className="min-h-screen bg-page text-slate-100">
      <Sidebar />
      <main className="ml-64 p-6">
        <div className="mx-auto max-w-[1900px]">
          <Header
            data={data}
            periodKey={periodKey}
            onPeriod={selectPeriod}
            channel={channel}
            onChannel={setChannel}
          />
          {error && (
            <div className="rounded-2xl border border-neg/40 bg-neg/10 p-4 text-rose-200">
              Failed to load business performance: {error}
            </div>
          )}
          {!data && !error && (
            <div className="font-mono text-xs uppercase tracking-widest text-slate-500">
              Loading…
            </div>
          )}
          {data && <Body data={data} channel={channel} />}
        </div>
      </main>
    </div>
  );
}

function Header({ data, periodKey, onPeriod, channel, onChannel }) {
  const period = data?.period;
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="flex items-center gap-2.5">
          <h1 className="font-display text-3xl font-bold tracking-tight text-slate-100">
            Business Performance
          </h1>
          <span
            title="Commercial finance lens — multi-week ordered value, channel mix, concentration, and product Pareto."
            className="text-slate-500"
          >
            <TrendingUp size={16} strokeWidth={2} />
          </span>
        </div>
        <p className="mt-1.5 font-mono text-[10px] uppercase tracking-widest text-slate-500">
          {period
            ? `w/c ${weekLongLabel(period.from)} → w/c ${weekLongLabel(period.to)} · ${period.n_weeks} week${period.n_weeks === 1 ? "" : "s"}`
            : "Commercial finance overview"}
        </p>
        {period?.prior_truncated && (
          <p className="mt-1 inline-flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest text-amber-300">
            <AlertTriangle size={11} strokeWidth={2} />
            Prior-period comparison unavailable — earlier weeks not yet imported
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <PeriodPicker value={periodKey} onSelect={onPeriod} />
        <ChannelToggle value={channel} onSelect={onChannel} />
      </div>
    </header>
  );
}

function PeriodPicker({ value, onSelect }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-800 bg-card p-0.5">
      {PERIOD_OPTIONS.map((o) => {
        const active = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onSelect(o.key)}
            className={
              "px-3 py-1.5 rounded-md font-display text-xs transition " +
              (active
                ? "bg-brand/15 text-brand"
                : "text-slate-400 hover:text-slate-100")
            }
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function ChannelToggle({ value, onSelect }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-800 bg-card p-0.5">
      {[
        { key: "wholesale", label: "Wholesale" },
        { key: "internal", label: "Internal" },
      ].map((o) => {
        const active = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onSelect(o.key)}
            className={
              "px-3 py-1.5 rounded-md font-display text-xs transition " +
              (active
                ? (o.key === "wholesale"
                    ? "bg-wholesale/20 text-purple-300"
                    : "bg-internal/20 text-blue-300")
                : "text-slate-400 hover:text-slate-100")
            }
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function Body({ data, channel }) {
  const customers = data.customers[channel];
  const concentration = data.concentration[channel];
  const hasPrior = !data.period.prior_truncated;

  return (
    <>
      <KpiRow data={data} channel={channel} concentration={concentration} />

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <BPWeeklyTrendChart rows={data.weekly_trend} />
        <BestWorstPanel stats={data.best_worst} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <BPCustomersTable
          payload={customers}
          channel={channel}
          hasPrior={hasPrior}
        />
        <WatchlistPanel
          customers={customers}
          concentration={concentration}
          channel={channel}
        />
      </div>

      <div className="mt-4">
        <BPProductPareto payload={data.products} />
      </div>

      <footer className="mt-8 flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 pt-4 font-mono text-[10px] uppercase tracking-widest text-slate-600">
        <span>
          Business Performance for w/c {weekLongLabel(data.period.from)} →
          {" "}w/c {weekLongLabel(data.period.to)}
        </span>
        <span>Ordered value · excl. VAT · external customers only</span>
      </footer>
    </>
  );
}

// ---------------------------------------------------------------------
// KPI tiles
// ---------------------------------------------------------------------

function KpiRow({ data, channel, concentration }) {
  const t = data.totals;
  const cur = t.current;
  const delta = t.delta;
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
      <KpiTile
        icon={PoundSterling}
        accent="brand"
        label="Period Ordered"
        value={gbp(cur.total)}
        deltaPct={delta?.total_pct}
        subline={
          delta
            ? `vs ${gbp(t.prior?.total)} prior ${data.period.n_weeks}w`
            : "No prior comparison available"
        }
      />
      <KpiTile
        icon={BarChart3}
        accent="brand"
        label="Weekly Run Rate"
        value={`${gbp(cur.avg_week)}/wk`}
        deltaPct={delta?.avg_week_pct}
        subline={
          delta
            ? `${gbp(t.prior?.avg_week)} prior period`
            : `${cur.distinct_orders} order${cur.distinct_orders === 1 ? "" : "s"} · ${cur.active_customers} active`
        }
      />
      <KpiTile
        icon={PieIcon}
        accent={channel === "wholesale" ? "wholesale" : "internal"}
        label="Channel Mix"
        value={`${pct(cur.wholesale_pct)} wholesale`}
        deltaPp={delta?.wholesale_share_pp}
        subline={`${pct(cur.internal_pct)} internal · ${gbp(cur.wholesale)} / ${gbp(cur.internal)}`}
      />
      <ConcentrationTile concentration={concentration} channel={channel} />
    </div>
  );
}

function KpiTile({ icon: Icon, accent = "brand", label, value, deltaPct, deltaPp, subline }) {
  const accentBg = {
    brand: "bg-brand/15 text-brand",
    wholesale: "bg-wholesale/20 text-purple-300",
    internal: "bg-internal/20 text-blue-300",
  }[accent] ?? "bg-brand/15 text-brand";

  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
            {label}
          </div>
          <div className="mt-2 font-display text-2xl font-semibold text-slate-100">
            {value}
          </div>
        </div>
        <div className={`flex h-9 w-9 items-center justify-center rounded-full ${accentBg}`}>
          <Icon size={16} strokeWidth={1.75} />
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 text-[11px]">
        <span className="font-mono text-slate-500">{subline}</span>
        {deltaPct !== undefined && deltaPct !== null ? (
          <DeltaPill value={deltaPct} suffix="%" />
        ) : deltaPp !== undefined && deltaPp !== null ? (
          <DeltaPill value={deltaPp} suffix="pp" />
        ) : null}
      </div>
    </div>
  );
}

function DeltaPill({ value, suffix }) {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  const up = n >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  const cls = up ? "text-pos bg-pos/10" : "text-neg bg-neg/10";
  const sign = up ? "+" : "";
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono tabular ${cls}`}>
      <Icon size={11} strokeWidth={2.5} />
      {sign}{n.toFixed(1)}{suffix}
    </span>
  );
}

function ConcentrationTile({ concentration, channel }) {
  const band = concentration?.band || "healthy";
  const bandStyle = {
    healthy:      { label: "Healthy",      cls: "bg-pos/15 text-pos" },
    watch:        { label: "Watch",        cls: "bg-amber-500/15 text-amber-300" },
    concentrated: { label: "Concentrated", cls: "bg-neg/15 text-neg" },
  }[band];
  return (
    <div className="relative overflow-hidden rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
            Concentration · {channel === "wholesale" ? "Wholesale" : "Internal"}
          </div>
          <div className="mt-2 font-display text-2xl font-semibold text-slate-100">
            {pct(concentration?.top_5_pct)}
            <span className="ml-1 font-mono text-xs text-slate-500">top-5</span>
          </div>
        </div>
        <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-800 text-slate-300">
          <ShieldAlert size={16} strokeWidth={1.75} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 font-mono text-[10px] uppercase tracking-widest text-slate-500">
        <ConcentrationRatio label="Top 1" value={concentration?.top_1_pct} />
        <ConcentrationRatio label="Top 3" value={concentration?.top_3_pct} />
        <ConcentrationRatio label="Top 5" value={concentration?.top_5_pct} />
      </div>
      <div className="mt-3 flex items-center justify-between text-[11px]">
        <span className="font-mono text-slate-500 truncate">
          {concentration?.top_1_name
            ? `Top: ${concentration.top_1_name}`
            : `${concentration?.n_customers ?? 0} customers`}
        </span>
        <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono ${bandStyle.cls}`}>
          {bandStyle.label}
        </span>
      </div>
    </div>
  );
}

function ConcentrationRatio({ label, value }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 px-2 py-1.5 text-center">
      <div className="text-slate-500">{label}</div>
      <div className="mt-0.5 font-display text-sm font-semibold normal-case text-slate-100 tracking-normal">
        {pct(value)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Best / Worst weeks panel
// ---------------------------------------------------------------------

function BestWorstPanel({ stats }) {
  const best = stats?.best_week;
  const worst = stats?.worst_week;
  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20">
      <h3 className="font-display text-base font-semibold text-slate-100">
        Best & Worst Weeks
      </h3>
      <div className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-slate-500">
        Range of weekly ordered value · variability
      </div>
      <div className="mt-4 space-y-3">
        <StatRow
          label="Strongest week"
          value={best ? gbp(best.total) : "—"}
          sub={best ? `w/c ${weekLongLabel(best.week)}` : "No data in period"}
          accent="pos"
        />
        <StatRow
          label="Quietest week"
          value={worst ? gbp(worst.total) : "—"}
          sub={worst ? `w/c ${weekLongLabel(worst.week)}` : "No data in period"}
          accent="neg"
        />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 border-t border-slate-800 pt-4">
        <MiniStat label="Spread" value={gbp(stats?.spread)} />
        <MiniStat
          label="Variability"
          value={stats?.variability_pct !== null && stats?.variability_pct !== undefined
            ? `±${Number(stats.variability_pct).toFixed(1)}%`
            : "—"}
        />
      </div>
    </div>
  );
}

function StatRow({ label, value, sub, accent }) {
  const accentCls = {
    pos: "border-pos/30 bg-pos/5",
    neg: "border-neg/30 bg-neg/5",
  }[accent] ?? "border-slate-800 bg-slate-950/40";
  return (
    <div className={`rounded-lg border ${accentCls} p-3`}>
      <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
        {label}
      </div>
      <div className="mt-1 font-display text-lg font-semibold text-slate-100">
        {value}
      </div>
      <div className="mt-0.5 font-mono text-[10px] text-slate-500">
        {sub}
      </div>
    </div>
  );
}

function MiniStat({ label, value }) {
  return (
    <div>
      <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
        {label}
      </div>
      <div className="mt-1 font-display text-base font-semibold text-slate-100">
        {value}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------
// Watchlist (right rail on row 3)
// ---------------------------------------------------------------------

function WatchlistPanel({ customers, concentration, channel }) {
  const rows = customers?.rows || [];
  const newCustomers = rows.filter((r) => r.state === "new").slice(0, 4);
  const declining = rows
    .filter((r) => r.state === "declining")
    .sort((a, b) => Number(a.delta_pct) - Number(b.delta_pct))
    .slice(0, 4);
  const dormant = (customers?.dormant || []).slice(0, 4);
  const band = concentration?.band || "healthy";

  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20">
      <h3 className="font-display text-base font-semibold text-slate-100">
        Risk & Watchlist
      </h3>
      <div className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-slate-500">
        {channel === "wholesale" ? "Wholesale" : "Internal"} · automated signals
      </div>

      {band !== "healthy" && (
        <div className={`mt-4 rounded-lg border p-3 text-xs ${
          band === "concentrated"
            ? "border-neg/40 bg-neg/5 text-rose-200"
            : "border-amber-500/30 bg-amber-500/5 text-amber-200"
        }`}>
          <div className="flex items-start gap-2">
            <ShieldAlert size={14} strokeWidth={2} className="mt-0.5 shrink-0" />
            <span>
              Top-5 concentration at <strong>{pct(concentration?.top_5_pct)}</strong> —
              {" "}{band === "concentrated" ? "high single-customer dependency" : "watch threshold crossed"}.
            </span>
          </div>
        </div>
      )}

      <WatchlistSection
        title="New this period"
        icon={Sparkles}
        accent="brand"
        items={newCustomers.map((r) => ({
          name: r.name,
          tail: gbp(r.current),
        }))}
        empty="No new customers."
      />
      <WatchlistSection
        title="Declining accounts"
        icon={ArrowDownRight}
        accent="neg"
        items={declining.map((r) => ({
          name: r.name,
          tail: `${Number(r.delta_pct).toFixed(1)}%`,
        }))}
        empty="No accounts down >10%."
      />
      <WatchlistSection
        title="Dormant (was active)"
        icon={Users}
        accent="amber"
        items={dormant.map((d) => ({
          name: d.name,
          tail: `was ${gbp(d.prior)}`,
        }))}
        empty="No dormant accounts."
      />
    </div>
  );
}

function WatchlistSection({ title, icon: Icon, accent, items, empty }) {
  const tailCls = {
    brand: "text-brand",
    neg: "text-neg",
    amber: "text-amber-300",
  }[accent] ?? "text-slate-300";
  const iconCls = {
    brand: "text-brand",
    neg: "text-neg",
    amber: "text-amber-400",
  }[accent] ?? "text-slate-400";
  return (
    <div className="mt-4 border-t border-slate-800 pt-3">
      <div className="flex items-center gap-1.5">
        <Icon size={12} strokeWidth={2} className={iconCls} />
        <span className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
          {title}
        </span>
      </div>
      {items.length === 0 ? (
        <div className="mt-2 font-mono text-[11px] text-slate-600">{empty}</div>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {items.map((it, i) => (
            <li key={`${it.name}-${i}`} className="flex items-center justify-between gap-2 text-sm">
              <span className="truncate text-slate-200">{it.name}</span>
              <span className={`shrink-0 font-mono tabular text-xs ${tailCls}`}>{it.tail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
