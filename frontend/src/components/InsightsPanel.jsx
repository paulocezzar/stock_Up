import { gbp, pct } from "../lib/format.js";

// Insights derived from the live payload only. No invented prose, no
// fabricated "We forecast…" lines. When the data can't support an
// insight (e.g. no prev week) the line is dropped silently rather
// than rendering a placeholder.
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
  // WoW headline — only when prev exists AND we have a real pct.
  if (wow && wow.pct !== null && wow.pct !== undefined) {
    const dir = Number(wow.pct) >= 0 ? "up" : "down";
    const colour = Number(wow.pct) >= 0 ? "text-pos" : "text-neg";
    out.push(
      <li key="wow">
        Ordered total {gbp(total_ordered)} —{" "}
        <span className={`tabular ${colour}`}>{pct(wow.pct, { signed: true })}</span>{" "}
        {dir} on previous imported week ({gbp(wow.total)}).
      </li>,
    );
  }
  // Channel share — both sides are always present in the payload.
  if (internal && wholesale) {
    const lead =
      Number(internal.total) >= Number(wholesale.total) ? "internal" : "wholesale";
    const leadColour = lead === "internal" ? "text-internal" : "text-wholesale";
    const leadName = lead === "internal" ? "Internal" : "Wholesale";
    const leadPct = lead === "internal" ? internal.pct : wholesale.pct;
    out.push(
      <li key="channel">
        <span className={leadColour}>{leadName}</span> leads this week at{" "}
        <span className="tabular">{pct(leadPct)}</span> of ordered demand.
      </li>,
    );
  }
  // Top wholesale customer — drop the bullet if the channel is empty.
  const topW = (top_wholesale || [])[0];
  if (topW) {
    out.push(
      <li key="topw">
        Top wholesale customer: <span className="text-slate-100">{topW.name}</span> at{" "}
        <span className="tabular">{gbp(topW.value)}</span>{" "}
        ({pct(topW.pct)} of channel).
      </li>,
    );
  }
  // Top internal customer.
  const topI = (top_internal || [])[0];
  if (topI) {
    out.push(
      <li key="topi">
        Top internal customer: <span className="text-slate-100">{topI.name}</span> at{" "}
        <span className="tabular">{gbp(topI.value)}</span>{" "}
        ({pct(topI.pct)} of channel).
      </li>,
    );
  }
  // Best / worst day — only when there are non-zero days.
  if (highest_day && lowest_day) {
    out.push(
      <li key="days">
        Strongest day: {highest_day.date} ({gbp(highest_day.total)}); quietest:{" "}
        {lowest_day.date} ({gbp(lowest_day.total)}).
      </li>,
    );
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
        <ul className="space-y-2 text-sm text-slate-300 leading-relaxed list-disc list-inside marker:text-slate-600">
          {insights}
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
