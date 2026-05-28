import { useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { gbp, pct } from "../lib/format.js";

// Customer performance table for one channel. Per-customer state badge
// (new / growing / declining / stable) + delta vs prior period as an
// arrow + signed percent. Dormant customers come from a separate
// payload field (data.customers[channel].dormant) and live in the
// Watchlist panel — not in this table.
const STATE_STYLE = {
  new:       { label: "New",       cls: "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  growing:   { label: "Growing",   cls: "border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300" },
  declining: { label: "Declining", cls: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-300" },
  stable:    { label: "Stable",    cls: "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300" },
};

const INITIAL_VISIBLE = 10;

export default function BPCustomersTable({ payload, channel, hasPrior }) {
  const rows = payload?.rows || [];
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? rows : rows.slice(0, INITIAL_VISIBLE);
  const hidden = rows.length - visible.length;

  return (
    <section className="w-full rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-950 dark:text-slate-100">
            Customer Performance
          </h3>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {channel === "wholesale" ? "Wholesale" : "Internal"} ·
            {" "}{rows.length} active · ordered value vs prior period
          </div>
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="text-sm text-slate-500 dark:text-slate-400">
          No active customers in this period.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400">
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
                  className="border-b border-slate-100 transition-colors last:border-0 hover:bg-slate-50/80 dark:border-slate-800 dark:hover:bg-slate-800/50"
                >
                  <td className="py-2.5 pr-2 text-right tabular text-slate-400 dark:text-slate-500">
                    {i + 1}
                  </td>
                  <td className="py-2.5 px-2 font-medium text-slate-800 dark:text-slate-200">{r.name}</td>
                  <td className="py-2.5 px-2 text-right tabular font-semibold text-slate-950 whitespace-nowrap dark:text-slate-100">
                    {gbp(r.current)}
                  </td>
                  <td className="py-2.5 px-2 text-right tabular text-slate-500 dark:text-slate-400">
                    {pct(r.share_pct)}
                  </td>
                  <td className="py-2.5 px-2 text-right">
                    <DeltaCell state={r.state} deltaPct={r.delta_pct} />
                  </td>
                  <td className="py-2.5 pl-2 text-right">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-xs font-semibold ${state.cls}`}
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
          className="mt-3 inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-800 dark:hover:text-white"
        >
          Show {hidden} more
        </button>
      )}
    </section>
  );
}

function DeltaCell({ state, deltaPct }) {
  if (state === "new") {
    return <span className="text-xs font-semibold text-slate-500">New</span>;
  }
  if (deltaPct === null || deltaPct === undefined) {
    return <span className="text-slate-400">—</span>;
  }
  const n = Number(deltaPct);
  if (!Number.isFinite(n)) {
    return <span className="text-slate-400">—</span>;
  }
  if (Math.abs(n) < 0.05) {
    return (
      <span className="inline-flex items-center justify-end gap-1 tabular text-slate-500">
        <Minus size={13} strokeWidth={2} />
        0.0%
      </span>
    );
  }
  const Icon = n > 0 ? ArrowUpRight : ArrowDownRight;
  const cls = n > 0 ? "text-emerald-700" : "text-rose-700";
  const sign = n > 0 ? "+" : "";
  return (
    <span className={`inline-flex items-center justify-end gap-1 tabular font-semibold ${cls}`}>
      <Icon size={13} strokeWidth={2.25} />
      {sign}{n.toFixed(1)}%
    </span>
  );
}
