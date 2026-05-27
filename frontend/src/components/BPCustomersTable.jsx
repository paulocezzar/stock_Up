import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { gbp, pct } from "../lib/format.js";

// Customer performance table for one channel. Per-customer state badge
// (new / growing / declining / stable) + delta vs prior period as an
// arrow + signed percent. Dormant customers come from a separate
// payload field (data.customers[channel].dormant) and live in the
// Watchlist panel — not in this table.
const STATE_STYLE = {
  new:       { label: "New",       cls: "bg-brand/15 text-brand" },
  growing:   { label: "Growing",   cls: "bg-pos/15 text-pos" },
  declining: { label: "Declining", cls: "bg-neg/15 text-neg" },
  stable:    { label: "Stable",    cls: "bg-slate-800 text-slate-300" },
};

const INITIAL_VISIBLE = 10;

export default function BPCustomersTable({ payload, channel, hasPrior }) {
  const rows = payload?.rows || [];
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? rows : rows.slice(0, INITIAL_VISIBLE);
  const hidden = rows.length - visible.length;

  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-100">
            Customer Performance
          </h3>
          <div className="mt-0.5 font-mono text-[10px] uppercase tracking-widest text-slate-500">
            {channel === "wholesale" ? "Wholesale" : "Internal"} ·
            {" "}{rows.length} active · ordered value vs prior period
          </div>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">
          No active customers in this period.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800 text-left font-mono text-[10px] uppercase tracking-widest text-slate-500">
              <th className="w-8 py-2.5 pr-2 text-right">#</th>
              <th className="py-2.5 px-2">Customer</th>
              <th className="py-2.5 px-2 text-right">Value</th>
              <th className="py-2.5 px-2 text-right">Share</th>
              <th className="py-2.5 px-2 text-right">{hasPrior ? "Δ vs prior" : "Δ"}</th>
              <th className="py-2.5 pl-2 text-right">State</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((r, i) => {
              const state = STATE_STYLE[r.state] || STATE_STYLE.stable;
              return (
                <tr
                  key={r.customer_id ?? `${r.name}-${i}`}
                  className="border-b border-slate-900 transition last:border-0 hover:bg-slate-900/40"
                >
                  <td className="py-2.5 pr-2 text-right font-mono tabular text-slate-500">
                    {i + 1}
                  </td>
                  <td className="py-2.5 px-2 text-slate-200">{r.name}</td>
                  <td className="py-2.5 px-2 text-right font-mono tabular text-slate-100 whitespace-nowrap">
                    {gbp(r.current)}
                  </td>
                  <td className="py-2.5 px-2 text-right font-mono tabular text-slate-400">
                    {pct(r.share_pct)}
                  </td>
                  <td className="py-2.5 px-2 text-right">
                    <DeltaCell state={r.state} deltaPct={r.delta_pct} />
                  </td>
                  <td className="py-2.5 pl-2 text-right">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest ${state.cls}`}
                    >
                      {state.label}
                    </span>
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
          Show {hidden} more
        </button>
      )}
    </div>
  );
}

function DeltaCell({ state, deltaPct }) {
  if (state === "new") {
    return <span className="font-mono text-[11px] text-brand">NEW</span>;
  }
  if (deltaPct === null || deltaPct === undefined) {
    return <span className="font-mono text-slate-600">—</span>;
  }
  const n = Number(deltaPct);
  if (!Number.isFinite(n)) {
    return <span className="font-mono text-slate-600">—</span>;
  }
  if (Math.abs(n) < 0.05) {
    return (
      <span className="inline-flex items-center justify-end gap-1 font-mono tabular text-slate-400">
        <Minus size={13} strokeWidth={2} />
        0.0%
      </span>
    );
  }
  const Icon = n > 0 ? ArrowUpRight : ArrowDownRight;
  const cls = n > 0 ? "text-pos" : "text-neg";
  const sign = n > 0 ? "+" : "";
  return (
    <span className={`inline-flex items-center justify-end gap-1 font-mono tabular ${cls}`}>
      <Icon size={13} strokeWidth={2.25} />
      {sign}{n.toFixed(1)}%
    </span>
  );
}
