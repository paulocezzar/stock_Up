import { gbp } from "../lib/format.js";

// Recent order groups (one row per customer-day). Channel badge is
// blue/purple per the design tokens; the bakery's own consumption
// surfaces as "excluded" and is dimmed so it stays visible without
// inflating the revenue read.
const CHANNEL_STYLE = {
  internal:  { label: "Internal",  bg: "bg-internal/15",  text: "text-internal" },
  wholesale: { label: "Wholesale", bg: "bg-wholesale/15", text: "text-wholesale" },
  excluded:  { label: "Excluded",  bg: "bg-slate-800/60", text: "text-slate-500" },
};

export default function RecentOrders({ rows }) {
  const data = rows || [];
  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="mb-3">
        <div className="font-display text-sm font-semibold text-slate-100">
          Recent Orders
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
          Latest customer-day groups across all weeks
        </div>
      </div>
      {data.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">No recent orders.</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left font-mono text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-800">
              <th className="py-2 pr-2">Date</th>
              <th className="py-2 px-2">Customer</th>
              <th className="py-2 px-2">Channel</th>
              <th className="py-2 px-2 text-right">Lines</th>
              <th className="py-2 pl-2 text-right">Ordered</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r, i) => {
              const c = CHANNEL_STYLE[r.channel] || CHANNEL_STYLE.excluded;
              return (
                <tr key={`${r.date}-${r.customer}-${i}`}
                    className="border-b border-slate-900 last:border-0">
                  <td className="py-2 pr-2 tabular text-slate-300">{r.date}</td>
                  <td className="py-2 px-2 text-slate-200">{r.customer}</td>
                  <td className="py-2 px-2">
                    <span className={`px-2 py-0.5 rounded font-mono text-[10px] uppercase tracking-widest ${c.bg} ${c.text}`}>
                      {c.label}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right tabular text-slate-400">
                    {r.line_count}
                  </td>
                  <td className="py-2 pl-2 text-right tabular text-slate-100">
                    {gbp(r.ordered_total)}
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
