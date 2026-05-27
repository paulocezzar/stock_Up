import { ChevronRight } from "lucide-react";
import { gbp } from "../lib/format.js";

// Top wholesale customers for the selected week. Rank column + a
// horizontal share-bar per row visualises each customer's slice of
// the channel (using the API's `pct` — real data, not a fabricated
// time series). No per-row daily sparkline: API doesn't expose
// per-customer daily totals; inventing one violates honest-data.
//
// Fixed table layout with an explicit <colgroup> so the £ column
// always gets enough room for the longest realistic value
// (~£1,xxx.xx) and the customer name truncates with ellipsis on a
// single line — never wraps, never clips the right edge of the card.
// Numeric Share % is dropped — the bar carries the comparison; the
// number is redundant in a narrow card.
export default function TopCustomersTable({ rows }) {
  const data = rows || [];
  const maxPct = Math.max(...data.map((r) => Number(r.pct) || 0), 0);
  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-100">
            Top Wholesale Customers
          </h3>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            By ordered value · this week
          </div>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest px-2 py-0.5 rounded-md bg-wholesale/15 text-wholesale">
          Wholesale
        </span>
      </div>
      {data.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">
          No wholesale customers in this week.
        </div>
      ) : (
        <table className="w-full table-fixed text-sm">
          <colgroup>
            <col style={{ width: "28px" }} />
            <col />
            <col style={{ width: "72px" }} />
            <col style={{ width: "92px" }} />
          </colgroup>
          <thead>
            <tr className="text-left font-mono text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-800">
              <th className="py-2 pr-2 text-right">#</th>
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
                  <td className="py-2 pr-2 text-right font-mono tabular text-slate-500">
                    {i + 1}
                  </td>
                  <td
                    className="py-2 px-2 text-slate-200 truncate"
                    title={r.name}
                  >
                    {r.name}
                  </td>
                  <td className="py-2 px-2">
                    <div className="h-1.5 rounded-full bg-slate-900 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-wholesale"
                        style={{ width }}
                      />
                    </div>
                  </td>
                  <td className="py-2 pl-2 text-right font-mono tabular text-slate-100 whitespace-nowrap">
                    {gbp(r.value)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      <div className="mt-3">
        <a
          href="/customers/"
          className="inline-flex items-center gap-1 text-xs font-display text-brand hover:underline"
        >
          View all customers
          <ChevronRight size={13} strokeWidth={2} />
        </a>
      </div>
    </div>
  );
}
