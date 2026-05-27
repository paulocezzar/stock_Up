import { Sun, Moon, PieChart as PieIcon, Crown } from "lucide-react";
import { gbp } from "../lib/format.js";

// Compact "Weekly Summary" panel. Pulls highest_day / lowest_day / top
// customers / leading channel straight from the payload. Each row
// renders only when the underlying data is present — no "—"
// placeholder rows pretending to be results.
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
    rows.push({
      icon: Sun, iconClass: "text-brand bg-brand/10",
      label: "Strongest day",
      value: `${highest_day.date} · ${gbp(highest_day.total)}`,
    });
  }
  if (lowest_day) {
    rows.push({
      icon: Moon, iconClass: "text-slate-400 bg-slate-800/60",
      label: "Quietest day",
      value: `${lowest_day.date} · ${gbp(lowest_day.total)}`,
    });
  }
  if (internal && wholesale) {
    const lead = Number(internal.total) >= Number(wholesale.total) ? "internal" : "wholesale";
    rows.push({
      icon: PieIcon,
      iconClass: lead === "internal"
        ? "text-internal bg-internal/10" : "text-wholesale bg-wholesale/10",
      label: "Leading channel",
      value: lead === "internal" ? "Internal" : "Wholesale",
    });
  }
  const topW = (top_wholesale || [])[0];
  if (topW) rows.push({
    icon: Crown, iconClass: "text-wholesale bg-wholesale/10",
    label: "Top wholesale",
    value: `${topW.name} · ${gbp(topW.value)}`,
  });
  const topI = (top_internal || [])[0];
  if (topI) rows.push({
    icon: Crown, iconClass: "text-internal bg-internal/10",
    label: "Top internal",
    value: `${topI.name} · ${gbp(topI.value)}`,
  });

  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm">
      <div className="mb-3">
        <h3 className="font-display text-base font-semibold text-slate-100">
          Weekly Summary
        </h3>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
          Pulled live from this week's data
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="font-mono text-xs text-slate-500">No data for this week.</div>
      ) : (
        <ul className="space-y-2.5">
          {rows.map(({ icon: Icon, iconClass, label, value }) => (
            <li key={label} className="flex items-center gap-3">
              <span className={`h-8 w-8 rounded-md flex items-center justify-center shrink-0 ${iconClass}`}>
                <Icon size={14} strokeWidth={2} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500">
                  {label}
                </div>
                <div className="text-sm text-slate-100 truncate">{value}</div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
