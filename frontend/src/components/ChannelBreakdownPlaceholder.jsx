import { Lock, Layers } from "lucide-react";

// Channel Breakdown card frame — distinct from the donut (which is
// just Internal vs Wholesale totals). This card is meant to surface
// the per-category split inside each channel once SaleProducts have
// categories assigned (Chunk 4). Rendering a duplicate of the donut
// here would mislead; rendering invented category bars would
// fabricate data. So this carries a centred "coming with category
// data" message instead.
export default function ChannelBreakdownPlaceholder() {
  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm flex flex-col">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-100">
            Channel Breakdown
          </h3>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Per-channel × per-category split
          </div>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-slate-600 flex items-center gap-1.5">
          <Lock size={11} strokeWidth={1.75} />
          Coming
        </span>
      </div>
      <div className="flex-1 min-h-[180px] rounded-xl border border-dashed border-slate-800 flex items-center justify-center p-6">
        <div className="text-center max-w-[220px]">
          <span className="inline-flex h-10 w-10 rounded-xl bg-slate-800/60 text-slate-500 items-center justify-center mb-3">
            <Layers size={18} strokeWidth={1.75} />
          </span>
          <div className="text-sm font-display text-slate-300">
            Channel detail
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-1">
            Coming with category data
          </div>
          <div className="text-xs text-slate-600 mt-3 leading-relaxed">
            SaleProduct categories aren't yet assigned. No duplicate donut
            here — when categories land, this surfaces per-channel detail.
          </div>
        </div>
      </div>
    </div>
  );
}
