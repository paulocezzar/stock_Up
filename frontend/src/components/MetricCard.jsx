import { Info } from "lucide-react";
import { pct as fmtPct } from "../lib/format.js";

// One headline KPI: label + big value + optional delta line. Optional
// inline amber sparkline (top-right) for cards backed by real daily
// data — `sparkline` must be a numeric array; omit it on cards whose
// metric isn't a time series we can plot honestly. The "i" glyph signals
// "hover for context" via the standard title attribute.
//
// `tone="neutral"` greys the value for placeholders ("Not tracked").
// Omitting `delta` collapses the delta row — no fake "—%".
export default function MetricCard({
  label,
  value,
  subline,
  delta,
  icon: Icon,
  tone = "default",
  sparkline,
  hint,
}) {
  const valueClass =
    tone === "neutral"
      ? "tabular text-xl font-semibold text-slate-500"
      : "tabular text-xl font-semibold text-slate-100";
  const deltaColor =
    delta === null || delta === undefined
      ? "text-slate-500"
      : Number(delta) >= 0
      ? "text-pos"
      : "text-neg";

  return (
    <div className="rounded-xl border border-slate-800 bg-card px-3 pt-3 pb-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="font-mono text-[10px] uppercase tracking-widest text-slate-500 truncate">
            {label}
          </span>
          {hint && (
            <Info
              size={10}
              strokeWidth={1.75}
              className="text-slate-600 shrink-0"
              aria-label={hint}
            >
              <title>{hint}</title>
            </Info>
          )}
        </div>
        {sparkline && sparkline.length > 1 ? (
          <Sparkline values={sparkline} />
        ) : (
          Icon && <Icon size={13} strokeWidth={1.5} className="text-slate-600 shrink-0" />
        )}
      </div>
      <div className={`mt-1.5 ${valueClass}`}>{value}</div>
      {(subline || (delta !== undefined && delta !== null)) && (
        <div className="mt-0.5 flex items-baseline gap-2 text-[11px]">
          {delta !== undefined && delta !== null && (
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

// Tiny SVG sparkline. 60×18 viewport; values normalized to that box.
// Single-hue amber, matches the brand colour. No axes, no labels —
// purely a glyph indicating the shape of this week's daily series.
function Sparkline({ values }) {
  const W = 60, H = 18;
  const nums = values.map((v) => Number(v) || 0);
  const max = Math.max(...nums);
  const min = Math.min(...nums);
  const range = Math.max(1e-9, max - min);
  const step = nums.length > 1 ? W / (nums.length - 1) : W;
  const points = nums
    .map((v, i) => `${(i * step).toFixed(1)},${(H - ((v - min) / range) * H).toFixed(1)}`)
    .join(" ");
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="shrink-0">
      <polyline
        points={points}
        fill="none"
        stroke="#f5a400"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
