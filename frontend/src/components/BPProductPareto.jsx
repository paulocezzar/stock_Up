import { useState } from "react";
import { gbp, pct } from "../lib/format.js";

// Product Pareto: which SKUs carry the period revenue. Sorted by VALUE
// descending. Default visible = enough rows to cross 80% cumulative
// (n_to_80pct from the API), then the rest collapse behind a "Show
// remaining N" button — so the operator's eye lands on the few SKUs
// that drive the business rather than scrolling 40 lines.
export default function BPProductPareto({ payload }) {
  const rows = payload?.rows || [];
  const nTo80 = payload?.n_to_80pct || 0;
  const [expanded, setExpanded] = useState(false);
  const defaultCount = Math.max(nTo80, Math.min(rows.length, 5));
  const visible = expanded ? rows : rows.slice(0, defaultCount);
  const hidden = rows.length - visible.length;

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-950">
            Product Revenue Pareto
          </h3>
          <div className="mt-1 text-xs text-slate-500">
            Sorted by ordered value · cumulative share of period revenue
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-xs font-semibold text-slate-500">
          <Chip label={`${payload?.n_products ?? 0} products`} />
          <Chip label={`top 5 · ${pct(payload?.top_5_share_pct)}`} />
          <Chip label={`top 10 · ${pct(payload?.top_10_share_pct)}`} />
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="text-sm text-slate-500">
          No products sold in this period.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
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
                  className="border-b border-slate-100 transition last:border-0 hover:bg-slate-50"
                >
                  <td className="py-2.5 pr-2 text-right tabular text-slate-400">
                    {i + 1}
                  </td>
                  <td className="py-2.5 px-2 font-medium text-slate-800">
                    {r.product}
                    {inPareto && (
                      <span
                        className="ml-2 inline-block rounded-full border border-amber-200 bg-amber-50 px-1.5 py-0.5 align-middle text-[10px] font-semibold text-amber-800"
                        title="In the top set that drives 80% of period revenue"
                      >
                        80/20
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 px-2 text-right tabular text-slate-500 whitespace-nowrap">
                    {formatQty(r.qty)}
                  </td>
                  <td className="py-2.5 px-2 text-right tabular font-semibold text-slate-950 whitespace-nowrap">
                    {gbp(r.value)}
                  </td>
                  <td className="py-2.5 px-2 text-right tabular text-slate-500">
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
      )}

      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="mt-3 inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950"
        >
          Show remaining {hidden}
        </button>
      )}
    </section>
  );
}

function CumulativeBar({ pctValue }) {
  const w = Math.max(0, Math.min(100, pctValue));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-32 rounded-full bg-slate-200">
        <div
          className="h-1.5 rounded-full bg-amber-500"
          style={{ width: `${w}%` }}
        />
      </div>
      <span className="tabular text-xs text-slate-500">
        {w.toFixed(1)}%
      </span>
    </div>
  );
}

function Chip({ label }) {
  return (
    <span className="rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5">
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
