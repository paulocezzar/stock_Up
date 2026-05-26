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
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-100">
            Product Revenue Pareto
          </h3>
          <div className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-slate-500">
            Sorted by ordered value · cumulative share of period revenue
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-slate-500">
          <Chip label={`${payload?.n_products ?? 0} products`} />
          <Chip label={`top 5 · ${pct(payload?.top_5_share_pct)}`} />
          <Chip label={`top 10 · ${pct(payload?.top_10_share_pct)}`} />
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">
          No products sold in this period.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left font-mono text-[10px] uppercase tracking-widest text-slate-500">
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
                  className="border-b border-slate-900 transition last:border-0 hover:bg-slate-900/40"
                >
                  <td className="py-2.5 pr-2 text-right font-mono tabular text-slate-500">
                    {i + 1}
                  </td>
                  <td className="py-2.5 px-2 text-slate-200">
                    {r.product}
                    {inPareto && (
                      <span
                        className="ml-2 inline-block rounded-full bg-brand/15 px-1.5 py-0.5 align-middle font-mono text-[9px] uppercase tracking-widest text-brand"
                        title="In the top set that drives 80% of period revenue"
                      >
                        80/20
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 px-2 text-right font-mono tabular text-slate-400 whitespace-nowrap">
                    {formatQty(r.qty)}
                  </td>
                  <td className="py-2.5 px-2 text-right font-mono tabular text-slate-100 whitespace-nowrap">
                    {gbp(r.value)}
                  </td>
                  <td className="py-2.5 px-2 text-right font-mono tabular text-slate-400">
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
          className="mt-3 inline-flex items-center gap-1 rounded-md border border-slate-800 bg-slate-950/40 px-2.5 py-1 font-mono text-[10px] uppercase tracking-widest text-slate-300 transition hover:border-brand/40 hover:text-brand"
        >
          Show remaining {hidden}
        </button>
      )}
    </div>
  );
}

function CumulativeBar({ pctValue }) {
  const w = Math.max(0, Math.min(100, pctValue));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-32 rounded-full bg-slate-900">
        <div
          className="h-1.5 rounded-full bg-brand"
          style={{ width: `${w}%` }}
        />
      </div>
      <span className="font-mono tabular text-xs text-slate-400">
        {w.toFixed(1)}%
      </span>
    </div>
  );
}

function Chip({ label }) {
  return (
    <span className="rounded-md border border-slate-800 bg-slate-950/40 px-2 py-0.5">
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
