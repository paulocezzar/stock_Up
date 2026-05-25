import {
  ResponsiveContainer,
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { Info } from "lucide-react";
import { gbp, weekdayShort } from "../lib/format.js";

// Single-week daily ordered area (amber + gradient fill) overlaid
// with a slate dashed line for the previous imported week's same
// weekdays. Both series come straight from /api/dashboard/summary/
// — no 7-day rolling average, no smoothing.
//
// The header carries the section title + a "Daily" period chip on the
// right. Below the title sits a single "Ordered" tab — Orders / Units
// / Margin% tabs from the reference are intentionally omitted because
// the API doesn't expose those series and faking them would violate
// the no-fabrication rule.
export default function DailyTrendChart({ rows, hasPrev }) {
  const data = (rows || []).map((r) => ({
    label: weekdayShort(r.date),
    date: r.date,
    this: Number(r.total),
    prev: Number(r.prev_week_total),
  }));

  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-1.5">
            <h3 className="font-display text-base font-semibold text-slate-100">
              Daily Trend
            </h3>
            <span
              title="Ordered value per day this week vs the same weekday last week."
              className="text-slate-500"
            >
              <Info size={12} strokeWidth={2} />
            </span>
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Ordered · external customers · £ per day
          </div>
        </div>
        <span className="px-2.5 py-1 rounded-md bg-slate-900 text-slate-300 font-mono text-[10px] uppercase tracking-widest">
          Daily
        </span>
      </div>

      <div className="mb-3 inline-flex bg-slate-900/60 rounded-md p-0.5">
        <button
          type="button"
          className="px-3 py-1 rounded text-xs font-display bg-brand/15 text-brand cursor-default"
        >
          Ordered
        </button>
      </div>

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="trend-area" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f5a400" stopOpacity="0.45" />
                <stop offset="100%" stopColor="#f5a400" stopOpacity="0" />
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
              width={50}
            />
            <Tooltip cursor={{ stroke: "#1e293b", strokeWidth: 1 }} content={<TrendTooltip hasPrev={hasPrev} />} />
            <Area
              type="monotone"
              dataKey="this"
              name="This week"
              stroke="#f5a400"
              strokeWidth={3}
              fill="url(#trend-area)"
              dot={{ r: 3, fill: "#f5a400", stroke: "#0b111a", strokeWidth: 2 }}
              activeDot={{ r: 5, stroke: "#0b111a", strokeWidth: 2 }}
            />
            {hasPrev && (
              <Line
                type="monotone"
                dataKey="prev"
                name="Previous week"
                stroke="#64748b"
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 flex items-center gap-4 text-[11px] text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block w-3 h-0.5 bg-brand rounded" />
          This week
        </span>
        {hasPrev && (
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-0.5 border-t border-dashed border-slate-500" />
            Previous week
          </span>
        )}
      </div>
    </div>
  );
}

function TrendTooltip({ active, payload, label, hasPrev }) {
  if (!active || !payload || !payload.length) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  const thisVal = Number(row.this);
  const prevVal = Number(row.prev);
  const delta = thisVal - prevVal;
  const deltaPct = prevVal > 0 ? (delta / prevVal) * 100 : null;
  const deltaClass = delta >= 0 ? "text-pos" : "text-neg";
  return (
    <div className="rounded-md border border-slate-800 bg-card px-3 py-2 text-xs shadow-lg min-w-[170px]">
      <div className="font-display text-slate-200 mb-1.5">{label}</div>
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-slate-400">
          <span className="h-2 w-2 rounded-sm bg-brand" />
          This week
        </span>
        <span className="tabular text-slate-100">{gbp(thisVal)}</span>
      </div>
      {hasPrev && (
        <div className="flex items-center justify-between gap-3 mt-1">
          <span className="flex items-center gap-1.5 text-slate-500">
            <span className="h-2 w-2 rounded-sm bg-slate-500" />
            Last week
          </span>
          <span className="tabular text-slate-300">{gbp(prevVal)}</span>
        </div>
      )}
      {hasPrev && deltaPct !== null && (
        <div className={`mt-1.5 pt-1.5 border-t border-slate-800 tabular text-right ${deltaClass}`}>
          {delta >= 0 ? "+" : ""}{gbp(delta)} · {delta >= 0 ? "+" : ""}{deltaPct.toFixed(1)}%
        </div>
      )}
    </div>
  );
}
