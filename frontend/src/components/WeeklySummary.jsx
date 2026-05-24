import { gbp } from "../lib/format.js";

// Compact "Weekly Summary" panel. Pulls highest_day / lowest_day / top
// customers / busiest channel straight from the payload. Each row only
// renders when the underlying data is present — no "—" placeholder
// rows that pretend to be results.
export default function WeeklySummary({
  highest_day,
  lowest_day,
  top_wholesale,
  top_internal,
  internal,
  wholesale,
}) {
  const rows = [];
  if (highest_day) {
    rows.push({ k: "Strongest day", v: `${highest_day.date} · ${gbp(highest_day.total)}` });
  }
  if (lowest_day) {
    rows.push({ k: "Quietest day", v: `${lowest_day.date} · ${gbp(lowest_day.total)}` });
  }
  if (internal && wholesale) {
    const lead =
      Number(internal.total) >= Number(wholesale.total) ? "Internal" : "Wholesale";
    rows.push({ k: "Leading channel", v: lead });
  }
  const topW = (top_wholesale || [])[0];
  if (topW) rows.push({ k: "Top wholesale", v: `${topW.name} · ${gbp(topW.value)}` });
  const topI = (top_internal || [])[0];
  if (topI) rows.push({ k: "Top internal", v: `${topI.name} · ${gbp(topI.value)}` });

  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="mb-3">
        <div className="font-display text-sm font-semibold text-slate-100">
          Weekly Summary
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
          Pulled live from this week's data
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">No data for this week.</div>
      ) : (
        <dl className="space-y-2 text-sm">
          {rows.map((r) => (
            <div key={r.k} className="flex items-baseline justify-between gap-3">
              <dt className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
                {r.k}
              </dt>
              <dd className="text-slate-100 text-right truncate">{r.v}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
