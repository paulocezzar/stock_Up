import { gbp, pct } from "../lib/format.js";

// Top wholesale customers for the selected week. The API gives name,
// value, pct already — the dashboard rule is to omit any column the
// payload can't fill (no fake "vs last week" deltas).
export default function TopCustomersTable({ rows }) {
  const data = rows || [];
  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="font-display text-sm font-semibold text-slate-100">
            Top Wholesale Customers
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            By ordered value · this week
          </div>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-wholesale">
          Wholesale
        </span>
      </div>
      {data.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">
          No wholesale customers in this week.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left font-mono text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-800">
              <th className="py-2 pr-2">Customer</th>
              <th className="py-2 px-2 text-right">Ordered</th>
              <th className="py-2 pl-2 text-right">Share</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => (
              <tr key={r.name} className="border-b border-slate-900 last:border-0">
                <td className="py-2 pr-2 text-slate-200">{r.name}</td>
                <td className="py-2 px-2 text-right tabular text-slate-100">
                  {gbp(r.value)}
                </td>
                <td className="py-2 pl-2 text-right tabular text-slate-400">
                  {pct(r.pct)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
