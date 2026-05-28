import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { Info } from "lucide-react";
import { gbp, pct, weekLabel } from "../lib/format.js";

// Two-line ordered value chart over the selected period. Lines make
// Wholesale vs Internal easier to compare than stacked areas.
//
// No "previous period" overlay here — period-over-period comparison is
// handled by the KPI tiles. A second area for the prior period would
// clutter a multi-week chart with limited width.
export default function BPWeeklyTrendChart({ rows, mode = "weekly", className = "" }) {
  const isDaily = mode === "daily";
  const title = isDaily ? "Daily Ordered Value" : "Weekly Ordered Value";
  const grain = isDaily ? "Daily" : "Weekly";
  const data = (rows || []).map((r) => ({
    label: isDaily ? dayLabel(r.date) : weekLabel(r.week),
    tooltipLabel: isDaily ? dayTooltipLabel(r.date) : `w/c ${weekLabel(r.week)}`,
    keyDate: isDaily ? r.date : r.week,
    wholesale: Number(r.wholesale),
    internal: Number(r.internal),
    total: Number(r.total),
    priorTotal: r.prior_total === null || r.prior_total === undefined ? null : Number(r.prior_total),
    wholesaleShare: Number(r.total) ? Number(r.wholesale) / Number(r.total) * 100 : 0,
    internalShare: Number(r.total) ? Number(r.internal) / Number(r.total) * 100 : 0,
  }));
  const totals = data.reduce((acc, row) => ({
    wholesale: acc.wholesale + row.wholesale,
    internal: acc.internal + row.internal,
    total: acc.total + row.total,
  }), { wholesale: 0, internal: 0, total: 0 });

  return (
    <section className={`flex h-full w-full flex-col rounded-xl border border-slate-200 bg-white px-5 pb-2.5 pt-5 shadow-sm dark:border-slate-800 dark:bg-slate-900 ${className}`}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5">
            <h3 className="font-display text-base font-semibold text-slate-950 dark:text-slate-100">
              {title}
            </h3>
            <span
              title={`Ordered value by ${isDaily ? "day" : "week"}, split into Wholesale and Internal lines.`}
              className="text-slate-400 dark:text-slate-500"
            >
              <Info size={12} strokeWidth={2} />
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">
            Selected {isDaily ? "week" : "period"} by channel, ordered value in GBP.
          </div>
        </div>
        <span className="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-950/60 dark:text-slate-400">
          {grain}
        </span>
      </div>

      {data.length === 0 ? (
        <div className={`flex ${isDaily ? "min-h-44" : "min-h-72"} flex-1 items-center justify-center rounded-lg border border-dashed border-slate-200 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400`}>
          No {isDaily ? "daily" : "weekly"} ordered value in this period.
        </div>
      ) : (
      <div className={`${isDaily ? "min-h-44" : "min-h-52"} flex-1`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#e2e8f0" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="label"
              stroke="#cbd5e1"
              tick={{ fill: "#64748b", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "#e2e8f0" }}
            />
            <YAxis
              stroke="#cbd5e1"
              tick={{ fill: "#64748b", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "#e2e8f0" }}
              tickFormatter={(v) =>
                v >= 1000 ? `£${(v / 1000).toFixed(1)}k` : `£${v}`
              }
              width={52}
            />
            <Tooltip
              cursor={{ stroke: "#94a3b8", strokeWidth: 1, strokeDasharray: "3 3" }}
              content={<BPTrendTooltip />}
            />
            <Line
              type="monotone"
              dataKey="wholesale"
              name="Wholesale"
              stroke="#6d28d9"
              strokeWidth={2.5}
              dot={{ r: 3, strokeWidth: 2, fill: "#ffffff" }}
              activeDot={{ r: 5, stroke: "#ffffff", strokeWidth: 2, fill: "#6d28d9" }}
            />
            <Line
              type="monotone"
              dataKey="internal"
              name="Internal"
              stroke="#0284c7"
              strokeWidth={2.5}
              dot={{ r: 3, strokeWidth: 2, fill: "#ffffff" }}
              activeDot={{ r: 5, stroke: "#ffffff", strokeWidth: 2, fill: "#0284c7" }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      )}

      <div className="mt-1 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-2 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400">
        <div className="flex items-center gap-4">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-4 rounded-sm bg-wholesale" />
          Wholesale
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-1 w-4 rounded-sm bg-internal" />
          Internal
        </span>
        </div>
        <span className="tabular text-slate-600 dark:text-slate-300">
          {isDaily ? "Week" : "Period"} total: {gbp(totals.total)} · Wholesale: {gbp(totals.wholesale)} · Internal: {gbp(totals.internal)}
        </span>
      </div>
    </section>
  );
}

function BPTrendTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="min-w-[220px] rounded-md border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-1.5 font-display font-semibold text-slate-950 dark:text-slate-100">{row.tooltipLabel}</div>
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-slate-400">
          <span className="h-2 w-2 rounded-sm bg-wholesale" />
          Wholesale
        </span>
        <span className="tabular text-slate-950 dark:text-slate-100">
          {gbp(row.wholesale)} · {row.wholesaleShare.toFixed(1)}%
        </span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-slate-400">
          <span className="h-2 w-2 rounded-sm bg-internal" />
          Internal
        </span>
        <span className="tabular text-slate-950 dark:text-slate-100">
          {gbp(row.internal)} · {row.internalShare.toFixed(1)}%
        </span>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-3 border-t border-slate-200 pt-1.5 dark:border-slate-800">
        <span className="font-display font-semibold text-slate-700 dark:text-slate-300">Total</span>
        <span className="tabular font-semibold text-slate-950 dark:text-slate-100">{gbp(row.total)}</span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-3">
        <span className="text-slate-500 dark:text-slate-400">Vs prior equivalent day</span>
        <span className={`tabular font-semibold ${deltaClass(row)}`}>
          {deltaText(row)}
        </span>
      </div>
    </div>
  );
}

function deltaText(row) {
  if (row.priorTotal === null || !Number.isFinite(row.priorTotal) || row.priorTotal === 0) {
    return "No prior";
  }
  return pct((row.total - row.priorTotal) / row.priorTotal * 100, { signed: true });
}

function deltaClass(row) {
  if (row.priorTotal === null || !Number.isFinite(row.priorTotal) || row.priorTotal === 0) {
    return "text-slate-500 dark:text-slate-400";
  }
  const delta = row.total - row.priorTotal;
  if (Math.abs(delta) < 0.005) return "text-slate-500 dark:text-slate-400";
  return delta > 0 ? "text-emerald-700 dark:text-emerald-300" : "text-rose-700 dark:text-rose-300";
}

function dayLabel(iso) {
  if (!iso) return "--";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", { weekday: "short" });
}

function dayTooltipLabel(iso) {
  if (!iso) return "--";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
}
