import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts";
import { gbp, weekLabel } from "../lib/format.js";

// Weekly demand trend — stacked bars (internal + wholesale per week).
// Sums to the per-week total straight out of the API (per_week_split).
// No data fabrication: if the API ever returned null channel splits we
// would render total-only here, but per_week_split always provides both.
export default function WeeklyTrend({ rows }) {
  const data = (rows || []).map((r) => ({
    week: r.week,
    label: weekLabel(r.week),
    internal: Number(r.internal),
    wholesale: Number(r.wholesale),
    total: Number(r.total),
  }));

  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="font-display text-sm font-semibold text-slate-100">
            Weekly ordered demand
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Internal + Wholesale stack · per week commencing
          </div>
        </div>
      </div>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
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
                background: "#0b1220",
                border: "1px solid #1e293b",
                fontSize: 12,
              }}
              labelStyle={{ color: "#e2e8f0" }}
              itemStyle={{ color: "#cbd5e1" }}
              formatter={(value, name) => [gbp(value), name]}
              labelFormatter={(label) => `Week ${label}`}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, color: "#94a3b8" }}
              iconType="square"
            />
            <Bar
              dataKey="internal"
              stackId="ordered"
              fill="#fbbf24"
              name="Internal"
            />
            <Bar
              dataKey="wholesale"
              stackId="ordered"
              fill="#9d6f00"
              name="Wholesale"
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
