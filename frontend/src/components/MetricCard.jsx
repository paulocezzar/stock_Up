import { ArrowUpRight, ArrowDownRight, Info } from "lucide-react";

// One headline KPI. Layout:
//   [circular accent badge]  Title (single line, ellipsis if needed)
//                            BIG MONO VALUE
//                            [↑/↓ arrow] +X.Y% vs last week   [sparkline]
//
// `accent` picks the badge ring colour: brand / internal / wholesale /
// pos / slate. `deltaSuffix` is "%" by default; pass "pp" for
// percentage-type metrics so a -2.1 delta renders as "↓2.1pp" rather
// than "↓2.1%". `sparkline` is only ever populated where a real daily
// series backs the metric (Total Ordered, Avg Daily Ordered).
// `tone="neutral"` greys the value for explicit placeholders.
const ACCENT_CLASSES = {
  brand:     "border-brand text-brand bg-brand/10",
  internal:  "border-internal text-internal bg-internal/10",
  wholesale: "border-wholesale text-wholesale bg-wholesale/10",
  pos:       "border-pos text-pos bg-pos/10",
  slate:     "border-slate-700 text-slate-400 bg-slate-800/60",
};

export default function MetricCard({
  label,
  value,
  delta,
  deltaSuffix = "%",
  deltaSubline,
  icon: Icon,
  accent = "slate",
  tone = "default",
  sparkline,
  hint,
}) {
  const badge = ACCENT_CLASSES[accent] || ACCENT_CLASSES.slate;
  const hasDelta = delta !== undefined && delta !== null;
  const up = hasDelta && Number(delta) >= 0;
  const ArrowIcon = up ? ArrowUpRight : ArrowDownRight;
  const deltaColor = !hasDelta ? "text-slate-500" : up ? "text-pos" : "text-neg";
  const valueColor = tone === "neutral" ? "text-slate-500" : "text-slate-100";

  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm">
      <div className="flex items-center gap-3">
        <div className={`h-10 w-10 shrink-0 rounded-full border-2 flex items-center justify-center ${badge}`}>
          {Icon && <Icon size={16} strokeWidth={2} />}
        </div>
        <div className="min-w-0 flex-1 flex items-center gap-1.5">
          <span className="text-[13px] text-slate-200 font-display truncate" title={label}>
            {label}
          </span>
          {hint && (
            <span title={hint} className="text-slate-500 cursor-help shrink-0">
              <Info size={11} strokeWidth={2} />
            </span>
          )}
        </div>
      </div>
      <div className={`mt-3 font-mono text-2xl font-semibold leading-none ${valueColor}`}>
        {value}
      </div>
      <div className="mt-3 flex items-center justify-between gap-2 text-[12px] whitespace-nowrap">
        {hasDelta ? (
          <span className="flex items-center gap-1.5">
            <ArrowIcon size={13} strokeWidth={2.5} className={deltaColor} />
            <span className={`font-mono tabular font-semibold ${deltaColor}`}>
              {up ? "+" : ""}{Number(delta).toFixed(1)}{deltaSuffix}
            </span>
            <span className="text-slate-500">vs last week</span>
          </span>
        ) : (
          <span className="text-slate-500 truncate">{deltaSubline || " "}</span>
        )}
        {sparkline && sparkline.length > 1 ? <Sparkline values={sparkline} /> : null}
      </div>
    </div>
  );
}

// Tiny SVG sparkline. 60×22; brand-amber stroke + soft fill. Values
// normalized to box height. Single-hue — no green/red colouring.
function Sparkline({ values }) {
  const W = 60, H = 22;
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
