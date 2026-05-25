import {
  Download,
  ArrowLeftRight,
  ChevronRight,
  FileSpreadsheet,
  CloudSun,
  AlertTriangle,
  Lock,
} from "lucide-react";

// Action stack. Active rows get a chevron + two-line label + brand
// hover; disabled rows keep the lock glyph + "Coming" tag so the
// operator can SEE the surface without clicking into a dead path.
// Single-column at this card width so labels don't wrap awkwardly.
export default function QuickActions({
  exportHref,
  prevWeek,
  onCompare,
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm">
      <div className="mb-3">
        <h3 className="font-display text-base font-semibold text-slate-100">
          Quick Actions
        </h3>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
          Operator shortcuts
        </div>
      </div>
      <div className="space-y-2">
        <ActiveAction
          as="a"
          href={exportHref}
          icon={Download}
          label="Export Orders"
          sub="Week CSV"
        />
        <ActiveAction
          as="button"
          onClick={onCompare}
          disabled={!prevWeek}
          icon={ArrowLeftRight}
          label="Compare Previous Week"
          sub={prevWeek ? `Go to w/c ${prevWeek}` : "No prior week"}
        />
        <DisabledAction icon={FileSpreadsheet} label="Generate Production Sheet" />
        <DisabledAction icon={CloudSun}         label="Forecast Tomorrow" />
        <DisabledAction icon={AlertTriangle}    label="Flag Abnormal Orders" />
      </div>
    </div>
  );
}

function ActiveAction({ as = "button", href, onClick, disabled, icon: Icon, label, sub }) {
  const className =
    "group w-full flex items-center gap-3 rounded-lg border border-slate-800 bg-page/60 hover:border-brand/40 hover:bg-brand/5 transition px-3 py-2.5 text-left disabled:opacity-40 disabled:hover:border-slate-800 disabled:hover:bg-page/60 disabled:cursor-not-allowed";
  const inner = (
    <>
      <span className="h-8 w-8 rounded-md bg-brand/15 text-brand flex items-center justify-center shrink-0">
        <Icon size={14} strokeWidth={1.75} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm text-slate-100 font-display leading-tight">{label}</div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5 truncate">
          {sub}
        </div>
      </div>
      <ChevronRight
        size={14}
        strokeWidth={1.75}
        className="text-slate-600 group-hover:text-brand transition shrink-0"
      />
    </>
  );
  if (as === "a") {
    return <a href={href} className={className}>{inner}</a>;
  }
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={className}>
      {inner}
    </button>
  );
}

function DisabledAction({ icon: Icon, label }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-slate-800/60 bg-page/40 px-3 py-2.5">
      <span className="h-8 w-8 rounded-md bg-slate-800/60 text-slate-600 flex items-center justify-center shrink-0">
        <Icon size={14} strokeWidth={1.75} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm text-slate-500 font-display leading-tight">{label}</div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-600 mt-0.5 flex items-center gap-1">
          <Lock size={9} strokeWidth={1.75} />
          Coming
        </div>
      </div>
    </div>
  );
}
