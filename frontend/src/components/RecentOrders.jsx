import { ChevronRight } from "lucide-react";
import { gbp } from "../lib/format.js";

// Recent order groups (one customer-day per row). Channel rendered as
// a FILLED pill in the design tokens — blue=internal, purple=wholesale,
// slate=excluded (the bakery's own consumption stays visible so it
// doesn't get silently dropped from the operator's view). No "Status"
// column — orders here don't have a status field; surfacing a fake
// "Completed" would violate honest-data rules.
const CHANNEL_STYLE = {
  internal:  { label: "Internal",  className: "bg-internal text-white" },
  wholesale: { label: "Wholesale", className: "bg-wholesale text-white" },
  excluded:  { label: "Excluded",  className: "bg-slate-700 text-slate-300" },
};

export default function RecentOrders({ rows }) {
  const data = rows || [];
  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-100">
            Recent Orders
          </h3>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Latest customer-day groups across all weeks
          </div>
        </div>
        <a
          href="/orders/"
          className="inline-flex items-center gap-1 text-xs font-display text-brand hover:underline"
        >
          View all orders
          <ChevronRight size={13} strokeWidth={2} />
        </a>
      </div>
      {data.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">No recent orders.</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left font-mono text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-800">
              <th className="py-2.5 pr-2">Date</th>
              <th className="py-2.5 px-2">Customer</th>
              <th className="py-2.5 px-2">Channel</th>
              <th className="py-2.5 px-2 text-right">Lines</th>
              <th className="py-2.5 px-2 text-right">Ordered</th>
              <th className="py-2.5 pl-2 w-6" aria-hidden="true"></th>
            </tr>
          </thead>
          <tbody>
            {data.map((r, i) => {
              const c = CHANNEL_STYLE[r.channel] || CHANNEL_STYLE.excluded;
              return (
                <tr key={`${r.date}-${r.customer}-${i}`}
                    className="border-b border-slate-900 last:border-0 hover:bg-slate-900/40 transition">
                  <td className="py-2.5 pr-2 font-mono tabular text-slate-300">{r.date}</td>
                  <td className="py-2.5 px-2 text-slate-200">{r.customer}</td>
                  <td className="py-2.5 px-2">
                    <span className={`inline-block px-2 py-0.5 rounded-full font-mono text-[10px] uppercase tracking-widest ${c.className}`}>
                      {c.label}
                    </span>
                  </td>
                  <td className="py-2.5 px-2 text-right font-mono tabular text-slate-400">
                    {r.line_count}
                  </td>
                  <td className="py-2.5 px-2 text-right font-mono tabular text-slate-100 whitespace-nowrap">
                    {gbp(r.ordered_total)}
                  </td>
                  <td className="py-2.5 pl-2 text-right">
                    <ChevronRight size={13} strokeWidth={1.75} className="inline text-slate-600" />
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
