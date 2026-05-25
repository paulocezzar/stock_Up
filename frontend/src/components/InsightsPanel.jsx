import {
  TrendingUp,
  TrendingDown,
  PieChart as PieIcon,
  Crown,
  Sun,
} from "lucide-react";
import { gbp, pct } from "../lib/format.js";

// Insights derived from the live payload only. No invented prose, no
// fabricated "We forecast…" lines. Each insight renders as
// icon + bold headline + grey subline, colour-coded by type
// (green/red for WoW direction, blue/purple for channel, brand-amber
// for "top of", slate for context). When the data can't support an
// insight (no prev week, empty channel) the row is dropped silently.
function buildInsights({
  total_ordered,
  wow,
  internal,
  wholesale,
  top_wholesale,
  top_internal,
  highest_day,
  lowest_day,
}) {
  const out = [];

  if (wow && wow.pct !== null && wow.pct !== undefined) {
    const up = Number(wow.pct) >= 0;
    out.push({
      key: "wow",
      icon: up ? TrendingUp : TrendingDown,
      iconClass: up ? "text-pos bg-pos/10" : "text-neg bg-neg/10",
      headline: (
        <>
          Ordered {gbp(total_ordered)} ·{" "}
          <span className={up ? "text-pos" : "text-neg"}>
            {pct(wow.pct, { signed: true })}
          </span>{" "}
          vs last week
        </>
      ),
      sub: <>Previous imported week: {gbp(wow.total)}.</>,
    });
  }

  if (internal && wholesale) {
    const lead = Number(internal.total) >= Number(wholesale.total)
      ? "internal" : "wholesale";
    const leadName = lead === "internal" ? "Internal" : "Wholesale";
    const leadPct = lead === "internal" ? internal.pct : wholesale.pct;
    const followName = lead === "internal" ? "Wholesale" : "Internal";
    const followPct = lead === "internal" ? wholesale.pct : internal.pct;
    out.push({
      key: "channel",
      icon: PieIcon,
      iconClass: lead === "internal"
        ? "text-internal bg-internal/10"
        : "text-wholesale bg-wholesale/10",
      headline: (
        <>
          <span className={lead === "internal" ? "text-internal" : "text-wholesale"}>
            {leadName}
          </span>{" "}
          leads at {pct(leadPct)}
        </>
      ),
      sub: <>{followName} share: {pct(followPct)}.</>,
    });
  }

  const topW = (top_wholesale || [])[0];
  if (topW) {
    out.push({
      key: "topw",
      icon: Crown,
      iconClass: "text-wholesale bg-wholesale/10",
      headline: (
        <>
          Top wholesale: <span className="text-slate-100">{topW.name}</span>
        </>
      ),
      sub: <>{gbp(topW.value)} · {pct(topW.pct)} of channel.</>,
    });
  }

  const topI = (top_internal || [])[0];
  if (topI) {
    out.push({
      key: "topi",
      icon: Crown,
      iconClass: "text-internal bg-internal/10",
      headline: (
        <>
          Top internal: <span className="text-slate-100">{topI.name}</span>
        </>
      ),
      sub: <>{gbp(topI.value)} · {pct(topI.pct)} of channel.</>,
    });
  }

  if (highest_day && lowest_day) {
    out.push({
      key: "days",
      icon: Sun,
      iconClass: "text-brand bg-brand/10",
      headline: (
        <>
          Strongest day: <span className="text-slate-100">{highest_day.date}</span>{" "}
          ({gbp(highest_day.total)})
        </>
      ),
      sub: <>Quietest: {lowest_day.date} ({gbp(lowest_day.total)}).</>,
    });
  }

  return out;
}

export default function InsightsPanel(props) {
  const insights = buildInsights(props);
  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="mb-3">
        <div className="font-display text-sm font-semibold text-slate-100">
          Insights
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
          Computed from this week's data
        </div>
      </div>
      {insights.length > 0 ? (
        <ul className="space-y-2.5">
          {insights.map(({ key, icon: Icon, iconClass, headline, sub }) => (
            <li key={key} className="flex items-start gap-3">
              <span className={`shrink-0 h-7 w-7 rounded-md flex items-center justify-center ${iconClass}`}>
                <Icon size={14} strokeWidth={1.75} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-sm text-slate-100 font-display leading-tight">
                  {headline}
                </div>
                <div className="text-xs text-slate-500 mt-0.5">{sub}</div>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="font-mono text-xs text-slate-500">
          No data for this week.
        </div>
      )}
      <div className="mt-4 pt-3 border-t border-slate-800">
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-600">
          Forecast · Coming soon
        </div>
        <div className="text-xs text-slate-600 mt-1">
          Needs production history (Chunk 4) before forecasts can be honest.
        </div>
      </div>
    </div>
  );
}
