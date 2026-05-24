import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
  Legend,
} from "recharts";
import { gbp, pct } from "../lib/format.js";

// Two-slice donut: Internal (blue) vs Wholesale (purple). Values come
// straight from the channel-split payload — no client recomputation.
export default function ChannelSplitDonut({ internal, wholesale }) {
  const data = [
    { name: "Internal",  value: Number(internal?.total)  || 0, color: "#1473ff" },
    { name: "Wholesale", value: Number(wholesale?.total) || 0, color: "#7c3aed" },
  ];
  const total = data.reduce((s, d) => s + d.value, 0);

  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="mb-3">
        <div className="font-display text-sm font-semibold text-slate-100">
          Channel Split
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
          External ordered · Internal vs Wholesale
        </div>
      </div>
      <div className="h-56 relative">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={55}
              outerRadius={85}
              paddingAngle={2}
              stroke="#0b111a"
              strokeWidth={2}
            >
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "#0b111a",
                border: "1px solid #1e293b",
                fontSize: 12,
              }}
              itemStyle={{ color: "#cbd5e1" }}
              formatter={(v, n) => [gbp(v), n]}
            />
            <Legend
              wrapperStyle={{ fontSize: 11, color: "#94a3b8" }}
              iconType="square"
            />
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="tabular text-lg font-semibold text-slate-100">
            {gbp(total)}
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
            Total
          </div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <ChannelRow color="#1473ff" name="Internal"
                    total={internal?.total} pct={internal?.pct} />
        <ChannelRow color="#7c3aed" name="Wholesale"
                    total={wholesale?.total} pct={wholesale?.pct} />
      </div>
    </div>
  );
}

function ChannelRow({ color, name, total, pct: p }) {
  return (
    <div className="flex items-center gap-2">
      <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
      <span className="text-slate-300">{name}</span>
      <span className="ml-auto tabular text-slate-100">{gbp(total)}</span>
      <span className="tabular text-slate-500">{pct(p)}</span>
    </div>
  );
}
