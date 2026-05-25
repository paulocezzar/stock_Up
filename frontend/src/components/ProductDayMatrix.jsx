// "Ordered by Product × Day" — top ~12 products by total ordered qty
// for the selected week, each row showing Mon..Sun qtys with amber
// saturation scaled to that ROW's max (the product's own peak day).
// This is DEMAND, not capacity. The single-hue amber ramp intentionally
// avoids any green/amber/red signal — those would imply capacity
// thresholds we don't have (Chunk 4).
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function formatQty(s) {
  // Server sends Decimal-as-string; keep trailing zeros off when whole.
  const n = Number(s);
  if (!Number.isFinite(n) || n === 0) return "";
  if (Number.isInteger(n)) return String(n);
  // Up to 3dp (matches OrderLine.qty_ordered's decimal_places=3); trim trailing zeros.
  return n.toFixed(3).replace(/\.?0+$/, "");
}

function cellStyle(qty, rowMax) {
  if (qty <= 0 || rowMax <= 0) {
    return { background: "transparent" };
  }
  // 8% floor so a non-zero cell is always visibly distinct from an
  // empty one even when it's tiny relative to the row's peak.
  const ratio = Math.max(0.08, qty / rowMax);
  return { background: `rgba(245, 164, 0, ${ratio.toFixed(3)})` };
}

export default function ProductDayMatrix({ rows }) {
  const data = rows || [];
  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="font-display text-sm font-semibold text-slate-100">
            Ordered by Product × Day
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Ordered quantity · this week · external customers
          </div>
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-600 text-right max-w-[180px]">
          Category view + capacity needs Chunk 4
        </div>
      </div>
      {data.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">
          No orders for this week.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left font-mono text-[10px] uppercase tracking-widest text-slate-500 border-b border-slate-800">
              <th className="py-2 pr-2">Product</th>
              {DAYS.map((d) => (
                <th key={d} className="py-2 px-1 text-center">{d}</th>
              ))}
              <th className="py-2 pl-2 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {data.map((r) => {
              const daily = (r.daily || []).map(Number);
              const rowMax = Math.max(...daily, 0);
              return (
                <tr key={r.product} className="border-b border-slate-900 last:border-0">
                  <td className="py-2 pr-2 text-slate-200 truncate max-w-[260px]">
                    {r.product}
                  </td>
                  {daily.map((q, i) => (
                    <td key={i} className="py-1 px-0.5">
                      <div
                        className="h-7 rounded flex items-center justify-center tabular text-[11px] text-slate-100"
                        style={cellStyle(q, rowMax)}
                        title={q > 0 ? `${r.product} · ${DAYS[i]}: ${formatQty(String(q))}` : `${DAYS[i]}: 0`}
                      >
                        {formatQty(String(q))}
                      </div>
                    </td>
                  ))}
                  <td className="py-2 pl-2 text-right tabular text-slate-100">
                    {formatQty(r.total_qty)}
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
