import { gbp, pct } from "../lib/format.js";

// Top wholesale customers for the selected week. Rank column + a
// horizontal share-bar per row visualises each customer's slice of
// the channel (using the API's `pct` field — real data, not a
// fabricated time series). The grid intentionally OMITS a per-row
// daily sparkline: the API doesn't expose per-customer daily totals,
// and inventing or extrapolating one would violate honest-data rules.
export default function TopCustomersTable({ rows }) {
  const data = rows || [];
  const maxPct = Math.max(...data.map((r) => Number(r.pct) || 0), 0);
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
        <span className="font-mono text-[10px] uppercase tracking-widest px-2 py-0.5 rounded bg-wholesale/15 text-wholesale">
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
              <th className="py-2 pr-2 w-8 text-right">#</th>
              <th className="py-2 px-2">Customer</th>
              <th className="py-2 px-2">Share</th>
              <th className="py-2 pl-2 text-right">Ordered</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r, i) => {
              const p = Number(r.pct) || 0;
              const width = maxPct > 0 ? `${Math.max(2, (p / maxPct) * 100).toFixed(1)}%` : "0%";
              return (
                <tr key={r.name} className="border-b border-slate-900 last:border-0">
                  <td className="py-2 pr-2 text-right tabular text-slate-500">
                    {i + 1}
                  </td>
                  <td className="py-2 px-2 text-slate-200 truncate max-w-[220px]">
                    {r.name}
                  </td>
                  <td className="py-2 px-2 min-w-[120px]">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 rounded-full bg-slate-900 overflow-hidden">
                        <div
                          className="h-full rounded-full bg-wholesale"
                          style={{ width }}
                        />
                      </div>
                      <span className="tabular text-[11px] text-slate-400 w-10 text-right">
                        {pct(r.pct)}
                      </span>
                    </div>
                  </td>
                  <td className="py-2 pl-2 text-right tabular text-slate-100">
                    {gbp(r.value)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
