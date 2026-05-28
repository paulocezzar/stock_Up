import { useEffect, useState } from "react";
import { gbp, pct } from "../lib/format.js";

// Product Pareto: which SKUs carry the period ordered value. Sorted by VALUE
// descending. Default visible is the top 15 so the table stays scannable;
// the rest collapse behind a clear expand action.
const INITIAL_VISIBLE = 15;
export default function BPProductPareto({ payload }) {
  const rows = payload?.rows || [];
  const nTo80 = payload?.n_to_80pct || 0;
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? rows : rows.slice(0, INITIAL_VISIBLE);
  const hidden = rows.length - visible.length;

  useEffect(() => {
    setExpanded(false);
  }, [payload]);

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-950 dark:text-slate-100">
            Product Ordered Value
          </h3>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            Sorted by ordered value · cumulative share of period
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs font-semibold text-slate-500 dark:text-slate-400">
          <Chip label={`${payload?.n_products ?? 0} products`} />
          <Chip label={`top 5 · ${pct(payload?.top_5_share_pct)}`} />
          <Chip label={`top 10 · ${pct(payload?.top_10_share_pct)}`} />
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="text-sm text-slate-500 dark:text-slate-400">
          No products sold in this period.
        </div>
      ) : (
        <div className="rounded-lg border border-slate-100 dark:border-slate-800">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-white dark:bg-slate-900">
            <tr className="border-b border-slate-200 text-left text-xs font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400">
              <th className="w-8 py-2.5 pr-2 text-right">#</th>
              <th className="py-2.5 px-2">Product</th>
              <th className="py-2.5 px-2 text-right">Qty</th>
              <th className="py-2.5 px-2 text-right">Value</th>
              <th className="py-2.5 px-2 text-right">% period</th>
              <th className="py-2.5 pl-2">Cumulative</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => {
              const cum = Number(r.cumulative_pct);
              const inPareto = i + 1 <= nTo80;
              return (
                <tr
                  key={`${r.product}-${i}`}
                  className="border-b border-slate-100 transition last:border-0 hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/70"
                >
                  <td className="py-2.5 pr-2 text-right tabular text-slate-400 dark:text-slate-500">
                    {i + 1}
                  </td>
                  <td className="py-2.5 px-2 font-medium text-slate-800 dark:text-slate-200">
                    {r.product}
                    {inPareto && (
                      <span
                        className="ml-2 inline-block rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 align-middle text-[10px] font-semibold text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
                        title="In the top set that drives 80% of period ordered value"
                      >
                        80/20
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 px-2 text-right tabular text-slate-500 whitespace-nowrap dark:text-slate-400">
                    {formatQty(r.qty)}
                  </td>
                  <td className="py-2.5 px-2 text-right tabular font-semibold text-slate-950 whitespace-nowrap dark:text-slate-100">
                    {gbp(r.value)}
                  </td>
                  <td className="py-2.5 px-2 text-right tabular text-slate-500 dark:text-slate-400">
                    {pct(r.share_pct)}
                  </td>
                  <td className="py-2.5 pl-2">
                    <CumulativeBar pctValue={cum} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        </div>
      )}

      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-3 inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-800 dark:hover:text-white"
        >
          Show all products ({hidden} more)
        </button>
      )}
    </section>
  );
}

function CumulativeBar({ pctValue }) {
  const w = Math.max(0, Math.min(100, pctValue));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-32 rounded-full bg-slate-200 dark:bg-slate-800">
        <div
          className="h-1.5 rounded-full bg-amber-500"
          style={{ width: `${w}%` }}
        />
      </div>
      <span className="tabular text-xs text-slate-500 dark:text-slate-400">
        {w.toFixed(1)}%
      </span>
    </div>
  );
}

function Chip({ label }) {
  return (
    <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 dark:border-slate-800 dark:bg-slate-950/60">
      {label}
    </span>
  );
}

function formatQty(q) {
  const n = Number(q);
  if (!Number.isFinite(n)) return "—";
  // Whole-number qty (count) shows as integer; decimal qty (kg) shows
  // 2dp. Same heuristic the existing ProductDayMatrix uses.
  return Number.isInteger(n) ? n.toString() : n.toFixed(2);
}
