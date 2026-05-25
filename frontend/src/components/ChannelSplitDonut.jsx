import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Tooltip,
} from "recharts";
import { gbp, pct } from "../lib/format.js";

// Two-slice donut: Internal (blue) vs Wholesale (purple). Values come
// straight from the channel-split payload — no client recomputation.
// Thicker ring + larger centre stat than the default Recharts donut;
// horizontal mini-bars below the donut show the same numbers
// in a comparator shape (£ + %) so the eye can read share without
// counting pie slices.
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
      <div className="h-52 relative">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={60}
              outerRadius={96}
              paddingAngle={2}
              stroke="#0b111a"
              strokeWidth={3}
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
          </PieChart>
        </ResponsiveContainer>
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          <div className="tabular text-2xl font-semibold text-slate-100">
            {gbp(total)}
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Total ordered
          </div>
        </div>
      </div>
      <div className="mt-4 space-y-3">
        <ChannelBar color="#1473ff" name="Internal"
                    total={internal?.total} share={internal?.pct} />
        <ChannelBar color="#7c3aed" name="Wholesale"
                    total={wholesale?.total} share={wholesale?.pct} />
      </div>
    </div>
  );
}

function ChannelBar({ color, name, total, share }) {
  const sharePct = Math.max(0, Math.min(100, Number(share) || 0));
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs mb-1">
        <span className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: color }} />
          <span className="text-slate-300">{name}</span>
        </span>
        <span className="font-mono text-slate-500">
          <span className="tabular text-slate-100">{gbp(total)}</span>
          <span className="ml-2 tabular">{pct(share)}</span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-900 overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${sharePct}%`, background: color }}
        />
      </div>
    </div>
  );
}
