import {
  Download,
  ArrowLeftRight,
  FileSpreadsheet,
  CloudSun,
  AlertTriangle,
  Lock,
} from "lucide-react";

// Action grid. Only the wired actions are interactive; the rest render
// visibly disabled with a "coming" tag so the operator knows the
// surface but can't click into a dead path.
export default function QuickActions({
  exportHref,
  prevWeek,
  onCompare,
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="mb-3">
        <div className="font-display text-sm font-semibold text-slate-100">
          Quick Actions
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
          Operator shortcuts
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
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
    "flex items-start gap-3 rounded-md border border-slate-800 bg-page hover:border-brand/40 hover:bg-brand/5 transition px-3 py-3 text-left disabled:opacity-40 disabled:hover:border-slate-800 disabled:hover:bg-page disabled:cursor-not-allowed";
  const inner = (
    <>
      <Icon size={16} strokeWidth={1.5} className="text-brand mt-0.5" />
      <div className="min-w-0">
        <div className="text-sm text-slate-100 font-display">{label}</div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5 truncate">
          {sub}
        </div>
      </div>
    </>
  );
  if (as === "a") {
    return (
      <a href={href} className={className}>
        {inner}
      </a>
    );
  }
  return (
    <button type="button" onClick={onClick} disabled={disabled} className={className}>
      {inner}
    </button>
  );
}

function DisabledAction({ icon: Icon, label }) {
  return (
    <div className="flex items-start gap-3 rounded-md border border-slate-800/60 bg-page/60 px-3 py-3">
      <Icon size={16} strokeWidth={1.5} className="text-slate-600 mt-0.5" />
      <div className="min-w-0 flex-1">
        <div className="text-sm text-slate-500 font-display">{label}</div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-600 mt-0.5 flex items-center gap-1">
          <Lock size={9} strokeWidth={1.5} />
          Coming
        </div>
      </div>
    </div>
  );
}
