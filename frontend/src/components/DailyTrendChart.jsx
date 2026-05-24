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
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
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
              contentStyle={{
                background: "#0b111a",
                border: "1px solid #1e293b",
                fontSize: 12,
              }}
              labelStyle={{ color: "#e2e8f0" }}
              itemStyle={{ color: "#cbd5e1" }}
              formatter={(value, name) => [gbp(value), name]}
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
