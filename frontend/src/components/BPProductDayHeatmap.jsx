import { weekLongLabel } from "../lib/format.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function BPProductDayHeatmap({ rows, weekStart }) {
  const data = (rows || []).slice(0, 8);
  const maxQty = Math.max(
    0,
    ...data.flatMap((r) => (r.daily || []).map((q) => Number(q) || 0)),
  );

  return (
    <section className="self-start rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-950 dark:text-slate-100">
            Ordered by Product × Day
          </h3>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Ordered quantity · selected week · external customers
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            document
              .getElementById("product-ordered-value")
              ?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-800 dark:hover:text-white"
        >
          View all products
        </button>
      </div>

      {data.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
          No product demand for this selected week.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-[680px] w-full table-fixed text-xs">
            <colgroup>
              <col className="w-[34%]" />
              {DAYS.map((day) => (
                <col key={day} className="w-[7.5%]" />
              ))}
              <col className="w-[13.5%]" />
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 text-left font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400">
                <th className="py-1.5 pr-3">Product</th>
                {DAYS.map((day) => (
                  <th key={day} className="px-1 py-1.5 text-center">
                    {day}
                  </th>
                ))}
                <th className="py-1.5 pl-3 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => {
                const daily = normaliseDaily(row.daily);
                return (
                  <tr
                    key={row.product}
                    className="border-b border-slate-100 transition-colors last:border-0 hover:bg-slate-50/80 dark:border-slate-800 dark:hover:bg-slate-800/50"
                  >
                    <td
                      className="max-w-[260px] truncate py-1.5 pr-3 font-medium text-slate-700 dark:text-slate-200"
                      title={row.product}
                    >
                      {row.product}
                    </td>
                    {daily.map((qty, i) => (
                      <td key={`${row.product}-${DAYS[i]}`} className="px-1 py-1">
                        <div
                          className="flex h-6 w-full items-center justify-center rounded tabular text-[11px] font-semibold text-slate-950 ring-1 ring-inset ring-amber-900/5 dark:text-slate-100"
                          style={heatCellStyle(qty, maxQty)}
                          title={`${row.product} · ${dayTooltip(weekStart, i)} · ordered quantity: ${formatQty(qty) || "0"}`}
                        >
                          {formatQty(qty)}
                        </div>
                      </td>
                    ))}
                    <td className="py-1.5 pl-3 text-right tabular font-semibold text-slate-700 dark:text-slate-200">
                      {formatQty(Number(row.total_qty))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function normaliseDaily(daily) {
  const values = (daily || []).slice(0, 7).map((q) => Number(q) || 0);
  while (values.length < 7) values.push(0);
  return values;
}

function heatCellStyle(qty, maxQty) {
  if (qty <= 0 || maxQty <= 0) {
    return { background: "rgba(148, 163, 184, 0.08)", color: "transparent" };
  }
  const ratio = Math.max(0.12, qty / maxQty);
  return {
    background: `rgba(245, 164, 0, ${Math.min(0.9, ratio).toFixed(3)})`,
  };
}

function dayTooltip(weekStart, offset) {
  if (!weekStart) return DAYS[offset];
  const d = new Date(`${weekStart}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + offset);
  return `${DAYS[offset]} ${weekLongLabel(d.toISOString().slice(0, 10))}`;
}

function formatQty(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "";
  if (Number.isInteger(n)) return n.toString();
  return n.toFixed(3).replace(/\.?0+$/, "");
}
