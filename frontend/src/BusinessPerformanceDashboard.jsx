import { useCallback, useEffect, useState } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  AlertTriangle,
  BarChart3,
  ChevronDown,
  CircleDollarSign,
  Download,
  LineChart,
  PieChart as PieIcon,
  ShieldAlert,
  Sparkles,
  Users,
} from "lucide-react";
import Sidebar from "./components/Sidebar.jsx";
import BPWeeklyTrendChart from "./components/BPWeeklyTrendChart.jsx";
import BPCustomersTable from "./components/BPCustomersTable.jsx";
import BPProductPareto from "./components/BPProductPareto.jsx";
import BPProductDayHeatmap from "./components/BPProductDayHeatmap.jsx";
import {
  businessPerformanceExportUrl,
  fetchBusinessPerformance,
} from "./lib/api.js";
import {
  businessWeekLabel,
  businessWeekRangeLabel,
  gbp,
  pct,
  weekLabel,
  weekLongLabel,
  weekRangeLabel,
} from "./lib/format.js";

const PERIOD_OPTIONS = [
  { key: "current", label: "Current", weeks: 1 },
  { key: "4w", label: "4w", weeks: 4 },
  { key: "8w", label: "8w", weeks: 8 },
  { key: "12w", label: "12w", weeks: 12 },
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
  return { from: dateMinusWeeks(latest, opt.weeks - 1), to: latest };
}

export default function BusinessPerformanceDashboard() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [periodKey, setPeriodKey] = useState("current");
  const [channel, setChannel] = useState("wholesale");
  const [request, setRequest] = useState({});

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetchBusinessPerformance(request)
      .then((d) => {
        if (cancelled) return;
        setData(d);
      })
      .catch((e) => !cancelled && setError(e.message || String(e)));
    return () => { cancelled = true; };
  }, [periodKey, request]);

  const selectPeriod = useCallback((key) => {
    if (key === periodKey) return;
    setPeriodKey(key);
    if (!data?.period) return;
    setRequest(computeFromTo(
      key,
      data.period.earliest_imported,
      data.period.latest_imported,
    ));
  }, [data, periodKey]);

  const selectWeek = useCallback((week) => {
    if (!week) return;
    setPeriodKey("current");
    setRequest({ from: week, to: week });
  }, []);

  return (
    <div className="min-h-screen bg-[#f5f7fb] text-slate-950 dark:bg-slate-950 dark:text-slate-100">
      <Sidebar />
      <main className="ml-64 min-w-0">
        <div className="mx-auto w-full max-w-[1760px] px-8 py-7">
          <Header
            data={data}
            periodKey={periodKey}
            onPeriod={selectPeriod}
            onWeek={selectWeek}
            channel={channel}
            onChannel={setChannel}
            exportHref={data?.period ? businessPerformanceExportUrl({
              from: data.period.from,
              to: data.period.to,
            }) : businessPerformanceExportUrl()}
          />

          {error && (
            <div className="mb-5 rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200">
              Failed to load business performance: {error}
            </div>
          )}

          {!data && !error && (
            <div className="rounded-xl border border-slate-200 bg-white p-8 text-sm text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">
              Loading business performance...
            </div>
          )}

          {data && <Body data={data} channel={channel} />}
        </div>
      </main>
    </div>
  );
}

function Header({
  data, periodKey, onPeriod, onWeek, channel, onChannel, exportHref,
}) {
  const period = data?.period;
  return (
    <header className="mb-5 w-full">
      <div className="flex w-full flex-wrap items-center gap-x-5 gap-y-3">
        <div className="flex min-w-0 flex-wrap items-center gap-x-5 gap-y-2">
          <FilterGroup label="Range">
            <PeriodPicker value={periodKey} onSelect={onPeriod} />
          </FilterGroup>
          {periodKey === "current" && (
            <FilterGroup label="Week">
              <WeekSelect
                value={period?.from}
                options={data?.available_weeks || []}
                onSelect={onWeek}
              />
            </FilterGroup>
          )}
          <FilterGroup label="Channel">
            <ChannelToggle value={channel} onSelect={onChannel} />
          </FilterGroup>
          {period?.prior_truncated && (
            <span className="inline-flex items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2.5 py-1 text-xs text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
              <AlertTriangle size={12} strokeWidth={2} />
              Prior comparison limited
            </span>
          )}
          <a
            href={exportHref}
            className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:text-white"
            title="Download the selected Business Performance range as CSV."
          >
            <Download size={15} strokeWidth={1.8} />
            Export
          </a>
        </div>
      </div>
    </header>
  );
}

function FilterGroup({ label, children }) {
  return (
    <div className="flex items-center gap-2.5">
      <span className="text-sm font-medium text-slate-500 dark:text-slate-400">
        {label}
      </span>
      {children}
    </div>
  );
}

function PeriodPicker({ value, onSelect }) {
  return (
    <div className="inline-flex h-10 items-center rounded-lg border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      {PERIOD_OPTIONS.map((o) => {
        const active = o.key === value;
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onSelect(o.key)}
            className={
              "h-8 rounded-md px-3 text-sm font-medium transition " +
              (active
                ? "bg-slate-200 text-slate-950 shadow-sm dark:bg-slate-700 dark:text-white"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white")
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
    <div className="inline-flex h-10 items-center rounded-lg border border-slate-200 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900">
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
              "h-8 rounded-md px-3 text-sm font-medium transition " +
              (active
                ? "bg-amber-100 text-amber-900 dark:bg-amber-400/15 dark:text-amber-200"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white")
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
  const isSingleWeek = data.period?.n_weeks === 1;
  const isSingleSelectedWeek = data.period?.from && data.period.from === data.period.to;

  return (
    <div className="w-full">
      <KpiRow data={data} channel={channel} concentration={concentration} />
      <InsightStrip
        data={data}
        customers={customers}
        concentration={concentration}
      />
      <SignalStrip customers={customers} />

      <div className="mt-5 grid grid-cols-1 gap-5 xl:hidden">
        <BPWeeklyTrendChart
          rows={isSingleWeek ? data.daily_trend : data.weekly_trend}
          mode={isSingleWeek ? "daily" : "weekly"}
        />
        <ExecutiveSummary data={data} channel={channel} concentration={concentration} />
        <BPProductDayHeatmap
          mode={isSingleWeek ? "day" : "bucket"}
          weekStart={data.period?.from}
          rows={isSingleWeek
            ? data.product_day_matrix
            : data.product_week_matrix?.rows}
          buckets={isSingleWeek ? [] : (data.product_week_matrix?.buckets || [])}
          granularity={data.product_week_matrix?.granularity || "week"}
        />
        <WatchlistPanel
          customers={customers}
          concentration={concentration}
          channel={channel}
        />
        <BPCustomersTable
          payload={customers}
          channel={channel}
          hasPrior={hasPrior}
        />
      </div>

      <div className="mt-5 hidden gap-5 xl:grid xl:grid-cols-12 xl:items-stretch">
        <div className="col-span-8 min-w-0">
          <BPWeeklyTrendChart
            rows={isSingleWeek ? data.daily_trend : data.weekly_trend}
            mode={isSingleWeek ? "daily" : "weekly"}
            className="h-full"
          />
        </div>
        <div className="col-span-4 min-w-0">
          <ExecutiveSummary
            data={data}
            channel={channel}
            concentration={concentration}
            className="h-full"
          />
        </div>

        <div className="col-span-8 flex min-w-0 flex-col gap-5">
          <BPProductDayHeatmap
            mode={isSingleWeek ? "day" : "bucket"}
            weekStart={data.period?.from}
            rows={isSingleWeek
              ? data.product_day_matrix
              : data.product_week_matrix?.rows}
            buckets={isSingleWeek ? [] : (data.product_week_matrix?.buckets || [])}
            granularity={data.product_week_matrix?.granularity || "week"}
          />
          <BPCustomersTable
            payload={customers}
            channel={channel}
            hasPrior={hasPrior}
          />
        </div>
        <div className="col-span-4 min-w-0">
          <WatchlistPanel
            customers={customers}
            concentration={concentration}
            channel={channel}
          />
        </div>
      </div>

      <div id="product-ordered-value" className="mt-5 scroll-mt-6">
        <BPProductPareto payload={data.products} />
      </div>

      <footer className="mt-8 flex w-full flex-wrap items-center justify-between gap-2 border-t border-slate-200 pt-4 text-xs text-slate-700 dark:border-slate-800 dark:text-slate-200">
        <span>
          Business Performance for {isSingleSelectedWeek
            ? businessWeekRangeLabel(data.period.from, data.period.to)
            : weekRangeLabel(data.period.from, data.period.to)}
        </span>
        <span className="text-slate-600 dark:text-slate-300">Ordered value · excl. VAT · external customers only</span>
      </footer>
    </div>
  );
}

function InsightStrip({ data, customers, concentration }) {
  const rows = customers?.rows || [];
  const delta = data.totals?.delta;
  const topFaller = rows
    .filter((r) => Number.isFinite(Number(r.delta_pct)) && Number(r.delta_pct) < 0)
    .sort((a, b) => Number(a.delta_pct) - Number(b.delta_pct))[0];
  const mix = delta?.wholesale_share_pp != null
    ? `Wholesale ${pct(delta.wholesale_share_pp, { signed: true }).replace("%", "pp")}`
    : "No prior mix comparison";
  const concentrationText = `Top 5 customers drive ${pct(concentration?.top_5_pct)}`;
  const faller = topFaller
    ? `${topFaller.name} ${pct(topFaller.delta_pct, { signed: true })}`
    : "No declining account signal";
  const insights = [mix, concentrationText, faller].slice(0, 4);

  return (
    <section className="mt-5 w-full rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="mr-1 text-xs font-semibold tracking-normal text-slate-500 dark:text-slate-400">
          What changed?
        </span>
        {insights.map((insight) => (
          <span
            key={insight}
            className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 dark:border-slate-700 dark:bg-slate-950/50 dark:text-slate-300"
          >
            {insight}
          </span>
        ))}
      </div>
    </section>
  );
}

function WeekSelect({ value, options, onSelect }) {
  return (
    <div className="relative inline-flex h-10 items-center rounded-lg border border-slate-200 bg-white px-3 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <select
        value={value || ""}
        onChange={(e) => onSelect(e.target.value)}
        className="h-8 appearance-none bg-transparent pr-7 text-sm font-medium text-slate-700 outline-none dark:text-slate-300"
        aria-label="Select week"
      >
        {(options || []).map((iso) => (
          <option key={iso} value={iso}>
            {businessWeekLabel(iso)} · w/c {weekLongLabel(iso)}
          </option>
        ))}
      </select>
      <ChevronDown
        size={14}
        strokeWidth={1.8}
        className="pointer-events-none absolute right-3 text-slate-400"
      />
    </div>
  );
}

function SignalStrip({ customers }) {
  const rows = customers?.rows || [];
  const topRiser = rows
    .filter((r) => Number.isFinite(Number(r.delta_pct)) && Number(r.delta_pct) > 0)
    .sort((a, b) => Number(b.delta_pct) - Number(a.delta_pct))[0];
  const topFaller = rows
    .filter((r) => Number.isFinite(Number(r.delta_pct)) && Number(r.delta_pct) < 0)
    .sort((a, b) => Number(a.delta_pct) - Number(b.delta_pct))[0];

  return (
    <section className="mt-5 grid w-full grid-cols-1 gap-5 md:grid-cols-2">
      <SignalCard
        icon={ArrowUpRight}
        label="Top Riser"
        value={topRiser?.name || "--"}
        subline={topRiser ? `${pct(topRiser.delta_pct, { signed: true })} · ${gbp(topRiser.current)}` : "No rising accounts"}
        tone="positive"
      />
      <SignalCard
        icon={ArrowDownRight}
        label="Top Faller"
        value={topFaller?.name || "--"}
        subline={topFaller ? `${pct(topFaller.delta_pct, { signed: true })} · ${gbp(topFaller.current)}` : "No falling accounts"}
        tone="negative"
      />
    </section>
  );
}

function SignalCard({ icon: Icon, label, value, subline, tone = "neutral" }) {
  const toneCls = {
    neutral: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300",
    positive: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-300",
    negative: "bg-rose-50 text-rose-700 dark:bg-rose-500/10 dark:text-rose-300",
  }[tone];

  return (
    <div className="flex w-full min-w-0 items-start gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${toneCls}`}>
        <Icon size={17} strokeWidth={1.9} />
      </div>
      <div className="min-w-0">
        <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {label}
        </div>
        <div className="mt-1 truncate font-display text-base font-semibold text-slate-950 dark:text-slate-100" title={String(value)}>
          {value}
        </div>
        <div className="mt-1 truncate text-xs text-slate-500 dark:text-slate-400" title={subline}>
          {subline}
        </div>
      </div>
    </div>
  );
}

function KpiRow({ data, channel, concentration }) {
  const t = data.totals;
  const cur = t.current;
  const delta = t.delta;
  return (
    <div className="grid w-full grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-4">
      <KpiTile
        icon={CircleDollarSign}
        label="Period Ordered"
        value={gbp(cur.total)}
        deltaPct={delta?.total_pct}
        subline={delta ? `Prior ${gbp(t.prior?.total)}` : "No prior comparison"}
      />
      <KpiTile
        icon={LineChart}
        label="Weekly Run Rate"
        value={`${gbp(cur.avg_week)}/wk`}
        deltaPct={delta?.avg_week_pct}
        subline={`${cur.distinct_orders} orders · ${cur.active_customers} active customers`}
      />
      <KpiTile
        icon={PieIcon}
        label="Wholesale Share"
        value={pct(cur.wholesale_pct)}
        deltaPp={delta?.wholesale_share_pp}
        subline={`${pct(cur.internal_pct)} internal · ${gbp(cur.wholesale)} / ${gbp(cur.internal)}`}
      />
      <ConcentrationTile concentration={concentration} channel={channel} />
    </div>
  );
}

function KpiTile({ icon: Icon, label, value, deltaPct, deltaPp, subline }) {
  return (
    <div className="w-full rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {label}
          </div>
          <div className="mt-2 break-words font-display text-2xl font-semibold tracking-normal text-slate-950 dark:text-slate-100">
            {value}
          </div>
        </div>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-50 text-amber-700 dark:bg-amber-400/15 dark:text-amber-200">
          <Icon size={19} strokeWidth={1.8} />
        </div>
      </div>
      <div className="mt-4 flex min-h-6 items-center justify-between gap-3">
        <span className="truncate text-xs text-slate-500 dark:text-slate-400">{subline}</span>
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
  const cls = up
    ? "border-emerald-200 bg-emerald-50 text-emerald-700"
    : "border-rose-200 bg-rose-50 text-rose-700";
  const sign = up ? "+" : "";
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-semibold tabular ${cls}`}>
      <Icon size={13} strokeWidth={2.2} />
      {sign}{n.toFixed(1)}{suffix}
    </span>
  );
}

function ConcentrationTile({ concentration, channel }) {
  const band = concentration?.band || "healthy";
  const bandStyle = {
    healthy: { label: "Healthy", cls: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300" },
    watch: { label: "Watch", cls: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200" },
    concentrated: { label: "Concentrated", cls: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300" },
  }[band];

  return (
    <div className="w-full rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
            Concentration
          </div>
          <div className="mt-2 font-display text-2xl font-semibold tracking-normal text-slate-950 dark:text-slate-100">
            {pct(concentration?.top_5_pct)}
            <span className="ml-1 text-xs font-medium text-slate-500 dark:text-slate-400">top 5</span>
          </div>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
          <ShieldAlert size={19} strokeWidth={1.8} />
        </div>
      </div>
      <div className="mt-4 flex items-center justify-between gap-3">
        <span className="truncate text-xs text-slate-500 dark:text-slate-400">
          {channel === "wholesale" ? "Wholesale" : "Internal"} · top account:
          {" "}{concentration?.top_1_name || "none"}
        </span>
        <span className={`shrink-0 rounded-md border px-2 py-1 text-xs font-semibold ${bandStyle.cls}`}>
          {bandStyle.label}
        </span>
      </div>
    </div>
  );
}

function ExecutiveSummary({ data, channel, concentration, className = "" }) {
  const isSingleWeek = data.period?.n_weeks === 1;
  const current = data.totals?.current;
  const prior = data.totals?.prior;
  const delta = data.totals?.delta;
  const currentWeek = data.current_week;
  const best = data.best_worst?.best_week;
  const worst = data.best_worst?.worst_week;
  const projected = currentWeek?.projected_total
    ? `Projected ${gbp(currentWeek.projected_total)}`
    : currentWeek?.is_complete
      ? "Complete week"
      : "No projection yet";
  return (
    <section className={`flex h-full w-full flex-col rounded-xl border border-slate-200 bg-slate-50/70 p-5 dark:border-slate-800 dark:bg-slate-900/60 ${className}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-base font-semibold text-slate-950 dark:text-slate-100">
            Executive Summary
          </h2>
          <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
            {isSingleWeek
              ? "Selected week compared with prior and recent run rate."
              : "Highest, lowest, and dependency signals for this period."}
          </p>
        </div>
        <BarChart3 size={18} strokeWidth={1.8} className="text-slate-400 dark:text-slate-500" />
      </div>

      <div className="mt-5 space-y-3">
        {isSingleWeek ? (
          <>
            <SummaryRow
              label="Selected week"
              value={gbp(current?.total)}
              stacked
              sub={(
                <SummaryLines
                  lines={[
                    businessWeekLabel(data.period.from),
                    weekRangeLabel(data.period.from, data.period.to),
                    `${currentWeek?.days_covered || 0}/7 days covered · ${projected}`,
                  ]}
                />
              )}
            />
            <SummaryRow
              label="Prior week"
              value={prior ? gbp(prior.total) : "--"}
              stacked
              sub={prior ? (
                <SummaryLines
                  lines={[
                    businessWeekLabel(data.period.prior_from),
                    weekRangeLabel(data.period.prior_from, data.period.prior_to),
                  ]}
                />
              ) : "No prior comparison"}
            />
            <SummaryRow
              label="Change vs prior"
              value={delta?.total_pct != null ? pct(delta.total_pct, { signed: true }) : "--"}
              sub="Ordered value movement"
              tone={deltaTone(delta?.total_pct)}
            />
            <SummaryRow
              label="8w average"
              value={currentWeek?.avg_8w_total ? gbp(currentWeek.avg_8w_total) : "--"}
              sub={`${currentWeek?.avg_8w_weeks || 0} prior week${currentWeek?.avg_8w_weeks === 1 ? "" : "s"} in benchmark`}
            />
            <SummaryRow
              label="Pace vs 8w average"
              value={currentWeek?.vs_8w_pct != null ? pct(currentWeek.vs_8w_pct, { signed: true }) : "--"}
              sub={`Latest order date: ${currentWeek?.latest_order_date ? weekLabel(currentWeek.latest_order_date) : "--"}`}
              tone={deltaTone(currentWeek?.vs_8w_pct)}
            />
          </>
        ) : (
          <>
            <SummaryRow label="Strongest week" value={best ? gbp(best.total) : "--"} sub={best ? `w/c ${weekLongLabel(best.week)}` : "No data"} />
            <SummaryRow label="Quietest week" value={worst ? gbp(worst.total) : "--"} sub={worst ? `w/c ${weekLongLabel(worst.week)}` : "No data"} />
            <SummaryRow label="Spread" value={gbp(data.best_worst?.spread)} sub={`Variability ${data.best_worst?.variability_pct != null ? `+/-${Number(data.best_worst.variability_pct).toFixed(1)}%` : "--"}`} />
          </>
        )}
      </div>

      <div className="mt-5 rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/50">
        <div className="flex items-center justify-between gap-3 text-sm">
          <span className="font-medium text-slate-700 dark:text-slate-300">
            {channel === "wholesale" ? "Wholesale" : "Internal"} dependency
          </span>
          <span className="font-semibold text-slate-950 dark:text-slate-100">{pct(concentration?.top_1_pct)}</span>
        </div>
        <div className="mt-2 h-2 rounded-full bg-slate-200 dark:bg-slate-800">
          <div
            className="h-2 rounded-full bg-amber-500"
            style={{ width: `${Math.max(0, Math.min(100, Number(concentration?.top_1_pct) || 0))}%` }}
          />
        </div>
        <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">
          Top customer share: {concentration?.top_1_name || "none"}
        </p>
      </div>
    </section>
  );
}

function SummaryRow({ label, value, sub, tone = "neutral", stacked = false }) {
  const valueCls = {
    positive: "text-emerald-700 dark:text-emerald-300",
    negative: "text-rose-700 dark:text-rose-300",
    neutral: "text-slate-950 dark:text-slate-100",
    muted: "text-slate-500 dark:text-slate-400",
  }[tone] || "text-slate-950 dark:text-slate-100";

  if (stacked) {
    return (
      <div className="rounded-lg border border-slate-200 px-3 py-3 dark:border-slate-800">
        <div className="flex items-start justify-between gap-4">
          <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {label}
          </div>
          <div className={`shrink-0 text-right font-display text-lg font-semibold ${valueCls}`}>{value}</div>
        </div>
        <div className="mt-1.5 text-xs text-slate-600 dark:text-slate-300">{sub}</div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-slate-200 px-3 py-3 dark:border-slate-800">
      <div className="min-w-0">
        <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {label}
        </div>
        <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">{sub}</div>
      </div>
      <div className={`min-w-[104px] shrink-0 text-right font-display text-lg font-semibold ${valueCls}`}>{value}</div>
    </div>
  );
}

function SummaryLines({ lines }) {
  return (
    <div className="space-y-0.5 leading-snug">
      {lines.map((line, i) => (
        <div
          key={`${line}-${i}`}
          className={i === 0 ? "font-medium text-slate-700 dark:text-slate-200" : ""}
        >
          {line}
        </div>
      ))}
    </div>
  );
}

function deltaTone(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "muted";
  if (Math.abs(n) < 0.05) return "neutral";
  return n > 0 ? "positive" : "negative";
}

function WatchlistPanel({ customers, concentration, channel, className = "" }) {
  const rows = customers?.rows || [];
  const newCustomers = rows.filter((r) => r.state === "new").slice(0, 4);
  const declining = rows
    .filter((r) => r.state === "declining")
    .sort((a, b) => Number(a.delta_pct) - Number(b.delta_pct))
    .slice(0, 4);
  const dormant = (customers?.dormant || []).slice(0, 4);
  const band = concentration?.band || "healthy";

  return (
    <section className={`w-full rounded-xl border border-slate-200 bg-slate-50/70 p-5 dark:border-slate-800 dark:bg-slate-900/60 ${className}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-base font-semibold text-slate-950 dark:text-slate-100">
            Risk & Watchlist
          </h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {channel === "wholesale" ? "Wholesale" : "Internal"} customer signals.
          </p>
        </div>
        <button
          type="button"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-500 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-400 dark:hover:bg-slate-800"
          title="More watchlist actions"
        >
          <ChevronDown size={15} strokeWidth={1.8} />
        </button>
      </div>

      {band !== "healthy" && (
        <div className={`mt-4 rounded-lg border p-3 text-sm ${
          band === "concentrated"
            ? "border-rose-200 bg-rose-50 text-rose-700"
            : "border-amber-200 bg-amber-50 text-amber-800"
        }`}>
          <div className="flex items-start gap-2">
            <ShieldAlert size={15} strokeWidth={2} className="mt-0.5 shrink-0" />
            <span>
              Top-5 concentration is {pct(concentration?.top_5_pct)}.
            </span>
          </div>
        </div>
      )}

      <WatchlistSection
        title="New this period"
        icon={Sparkles}
        tone="amber"
        items={newCustomers.map((r) => ({ name: r.name, tail: gbp(r.current) }))}
        empty="No new customers."
      />
      <WatchlistSection
        title="Declining accounts"
        icon={ArrowDownRight}
        tone="rose"
        items={declining.map((r) => ({ name: r.name, tail: `${Number(r.delta_pct).toFixed(1)}%` }))}
        empty="No accounts down >10%."
      />
      <WatchlistSection
        title="Dormant accounts"
        icon={Users}
        tone="slate"
        items={dormant.map((d) => ({ name: d.name, tail: `was ${gbp(d.prior)}` }))}
        empty="No dormant accounts."
      />
    </section>
  );
}

function WatchlistSection({ title, icon: Icon, tone, items, empty }) {
  const toneCls = {
    amber: "text-amber-700 bg-amber-50",
    rose: "text-rose-700 bg-rose-50",
    slate: "text-slate-600 bg-slate-100",
  }[tone] ?? "text-slate-600 bg-slate-100";

  return (
    <div className="mt-4 border-t border-slate-200 pt-4 dark:border-slate-800">
      <div className="flex items-center gap-2">
        <span className={`flex h-6 w-6 items-center justify-center rounded-md ${toneCls}`}>
          <Icon size={13} strokeWidth={2} />
        </span>
        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
          {title}
        </span>
      </div>
      {items.length === 0 ? (
        <div className="mt-3 text-sm text-slate-400 dark:text-slate-500">{empty}</div>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.map((it, i) => (
            <li key={`${it.name}-${i}`} className="flex items-center justify-between gap-3 text-sm">
              <span className="min-w-0 truncate text-slate-700 dark:text-slate-300">{it.name}</span>
              <span className="shrink-0 tabular text-xs font-semibold text-slate-950 dark:text-slate-100">{it.tail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
