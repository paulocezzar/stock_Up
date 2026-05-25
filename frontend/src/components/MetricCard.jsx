import { ArrowUpRight, ArrowDownRight, Info } from "lucide-react";

// One headline KPI. Label + info "i" top-left, big DM Mono value, delta
// row (real WoW only — omit when no prior week), icon OR amber
// sparkline on the right (sparkline only when a real daily series
// backs the metric). `tone="neutral"` greys the value for explicit
// "Not tracked" placeholders.
export default function MetricCard({
  label,
  value,
  delta,
  deltaSubline,
  icon: Icon,
  tone = "default",
  sparkline,
  hint,
}) {
  const valueClass =
    tone === "neutral"
      ? "font-mono text-2xl font-semibold text-slate-500 leading-none mt-3"
      : "font-mono text-2xl font-semibold text-slate-100 leading-none mt-3";
  const hasDelta = delta !== undefined && delta !== null;
  const up = hasDelta && Number(delta) >= 0;
  const ArrowIcon = up ? ArrowUpRight : ArrowDownRight;
  const deltaColor = !hasDelta ? "text-slate-500" : up ? "text-pos" : "text-neg";

  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-1.5">
            <span className="text-[12px] text-slate-300 leading-snug">{label}</span>
            {hint && (
              <span title={hint} className="text-slate-500 cursor-help shrink-0 mt-0.5">
                <Info size={11} strokeWidth={2} />
              </span>
            )}
          </div>
          <div className={valueClass}>{value}</div>
          <div className="mt-2 flex items-center gap-1.5 text-[11px] min-h-[14px]">
            {hasDelta ? (
              <>
                <ArrowIcon size={12} strokeWidth={2.25} className={deltaColor} />
                <span className={`font-mono tabular ${deltaColor}`}>
                  {up ? "+" : ""}{Number(delta).toFixed(1)}%
                </span>
                <span className="text-slate-500 truncate">
                  {deltaSubline || "vs last week"}
                </span>
              </>
            ) : (
              <span className="text-slate-500 truncate">{deltaSubline || ""}</span>
            )}
          </div>
        </div>
        <div className="shrink-0">
          {sparkline && sparkline.length > 1 ? (
            <div className="h-9 px-2 rounded-lg bg-slate-900/60 border border-slate-800/60 flex items-center">
              <Sparkline values={sparkline} />
            </div>
          ) : (
            Icon && (
              <div className="h-9 w-9 rounded-lg bg-slate-900 border border-slate-800/60 flex items-center justify-center">
                <Icon size={16} strokeWidth={1.75} className="text-slate-400" />
              </div>
            )
          )}
        </div>
      </div>
    </div>
  );
}

// Tiny SVG sparkline. 64×28; brand-amber stroke + soft fill. Values
// normalized to box height. Single-hue — no green/red colouring.
function Sparkline({ values }) {
  const W = 64, H = 28;
  const nums = values.map((v) => Number(v) || 0);
  const max = Math.max(...nums);
  const min = Math.min(...nums);
  const range = Math.max(1e-9, max - min);
  const step = nums.length > 1 ? W / (nums.length - 1) : W;
  const pts = nums.map(
    (v, i) => `${(i * step).toFixed(1)},${(H - 2 - ((v - min) / range) * (H - 4)).toFixed(1)}`,
  );
  const linePoints = pts.join(" ");
  const fillPath = `M0,${H} L${pts.join(" L")} L${W},${H} Z`;
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="shrink-0">
      <defs>
        <linearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f5a400" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#f5a400" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={fillPath} fill="url(#spark-fill)" />
      <polyline
        points={linePoints}
        fill="none"
        stroke="#f5a400"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
