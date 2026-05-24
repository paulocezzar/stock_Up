import { pct as fmtPct } from "../lib/format.js";

// One headline KPI: label + big value + optional delta line.
// Pure presentational — never invents formatting. Caller passes the
// already-formatted value string so currency / percent rules live in
// one place (lib/format.js).
export default function MetricCard({
  label,
  value,
  subline,
  delta,
  icon: Icon,
}) {
  const deltaColor =
    delta === null || delta === undefined
      ? "text-slate-500"
      : Number(delta) >= 0
      ? "text-emerald-400"
      : "text-rose-400";
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950 p-4">
      <div className="flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
          {label}
        </div>
        {Icon && <Icon size={14} strokeWidth={1.5} className="text-slate-600" />}
      </div>
      <div className="mt-3 tabular text-2xl font-semibold text-slate-100">
        {value}
      </div>
      {(subline || delta !== undefined) && (
        <div className="mt-1 flex items-baseline gap-2 text-xs">
          {delta !== undefined && (
            <span className={`tabular ${deltaColor}`}>
              {fmtPct(delta, { signed: true })}
            </span>
          )}
          {subline && (
            <span className="text-slate-500 truncate">{subline}</span>
          )}
        </div>
      )}
    </div>
  );
}
