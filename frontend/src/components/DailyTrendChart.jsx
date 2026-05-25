import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts";
import { gbp, weekdayShort } from "../lib/format.js";

// Daily ordered total for the selected week (amber, solid) vs the
// previous imported week's same-weekday total (slate, dashed). Both
// series come straight from /api/dashboard/summary/?week=… — no
// 7-day rolling average synthesis.
export default function DailyTrendChart({ rows, hasPrev }) {
  const data = (rows || []).map((r) => ({
    label: weekdayShort(r.date),
    date: r.date,
    this: Number(r.total),
    prev: Number(r.prev_week_total),
  }));

  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="font-display text-sm font-semibold text-slate-100">
            Order Trend
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Daily ordered · this week vs previous imported week
          </div>
        </div>
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 8, right: 16, bottom: 0, left: 0 }}
          >
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
            <Tooltip
              cursor={{ stroke: "#1e293b", strokeWidth: 1 }}
              content={<TrendTooltip hasPrev={hasPrev} />}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, color: "#94a3b8" }}
              iconType="line"
            />
            <Line
              type="monotone"
              dataKey="this"
              name="This week"
              stroke="#f5a400"
              strokeWidth={2}
              dot={{ r: 3, fill: "#f5a400", strokeWidth: 0 }}
              activeDot={{ r: 5 }}
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
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

// Custom tooltip — shows This/Last side-by-side per day with the
// per-day delta (£ + %) when both numbers are present. When there's
// no previous week, the row degrades cleanly to just "This week".
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
    <div className="rounded-md border border-slate-800 bg-card px-3 py-2 text-xs shadow-lg min-w-[160px]">
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
