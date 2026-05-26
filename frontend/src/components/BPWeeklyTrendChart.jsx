import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { Info } from "lucide-react";
import { gbp, weekLabel } from "../lib/format.js";

// Stacked area: wholesale (top, purple) + internal (bottom, blue) over
// the selected period. Sister to DailyTrendChart but range-scoped —
// rows come from /api/business-performance/summary/weekly_trend, which
// is per_week_split serialised.
//
// No "previous period" overlay here — period-over-period comparison is
// handled by the KPI tiles. A second area for the prior period would
// clutter a multi-week chart with limited width.
export default function BPWeeklyTrendChart({ rows }) {
  const data = (rows || []).map((r) => ({
    label: weekLabel(r.week),
    week: r.week,
    wholesale: Number(r.wholesale),
    internal: Number(r.internal),
    total: Number(r.total),
  }));

  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-1.5">
            <h3 className="font-display text-base font-semibold text-slate-100">
              Weekly Revenue Trend
            </h3>
            <span
              title="Ordered value by week. Stacked: wholesale on top of internal."
              className="text-slate-500"
            >
              <Info size={12} strokeWidth={2} />
            </span>
          </div>
          <div className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-slate-500">
            Selected period · stacked by channel · £
          </div>
        </div>
        <span className="rounded-md bg-slate-900 px-2.5 py-1 font-mono text-[10px] uppercase tracking-widest text-slate-300">
          Weekly
        </span>
      </div>

      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="bp-internal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#1473ff" stopOpacity="0.55" />
                <stop offset="100%" stopColor="#1473ff" stopOpacity="0.05" />
              </linearGradient>
              <linearGradient id="bp-wholesale" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#7c3aed" stopOpacity="0.55" />
                <stop offset="100%" stopColor="#7c3aed" stopOpacity="0.05" />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#0f172a" strokeDasharray="2 4" vertical={false} />
            <XAxis
              dataKey="label"
              stroke="#475569"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "#1e293b" }}
            />
            <YAxis
              stroke="#475569"
              tick={{ fill: "#94a3b8", fontSize: 11 }}
              tickLine={false}
              axisLine={{ stroke: "#1e293b" }}
              tickFormatter={(v) =>
                v >= 1000 ? `£${(v / 1000).toFixed(1)}k` : `£${v}`
              }
              width={52}
            />
            <Tooltip cursor={{ stroke: "#1e293b", strokeWidth: 1 }} content={<BPTrendTooltip />} />
            <Area
              type="monotone"
              dataKey="internal"
              name="Internal"
              stackId="ch"
              stroke="#1473ff"
              strokeWidth={2}
              fill="url(#bp-internal)"
              activeDot={{ r: 4, stroke: "#0b111a", strokeWidth: 2 }}
            />
            <Area
              type="monotone"
              dataKey="wholesale"
              name="Wholesale"
              stackId="ch"
              stroke="#7c3aed"
              strokeWidth={2}
              fill="url(#bp-wholesale)"
              activeDot={{ r: 4, stroke: "#0b111a", strokeWidth: 2 }}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 flex items-center gap-4 text-[11px] text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 rounded-sm bg-wholesale" />
          Wholesale
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-3 rounded-sm bg-internal" />
          Internal
        </span>
      </div>
    </div>
  );
}

function BPTrendTooltip({ active, payload }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="min-w-[180px] rounded-md border border-slate-800 bg-card px-3 py-2 text-xs shadow-lg">
      <div className="mb-1.5 font-display text-slate-200">w/c {row.label}</div>
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-slate-400">
          <span className="h-2 w-2 rounded-sm bg-wholesale" />
          Wholesale
        </span>
        <span className="tabular text-slate-100">{gbp(row.wholesale)}</span>
      </div>
      <div className="mt-1 flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-slate-400">
          <span className="h-2 w-2 rounded-sm bg-internal" />
          Internal
        </span>
        <span className="tabular text-slate-100">{gbp(row.internal)}</span>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-3 border-t border-slate-800 pt-1.5">
        <span className="font-display text-slate-300">Total</span>
        <span className="tabular text-slate-100">{gbp(row.total)}</span>
      </div>
    </div>
  );
}
