import { Lock, Factory } from "lucide-react";

// Production Load card frame — explicitly a placeholder. The day ×
// category capacity heatmap needs product categories + per-category
// capacity input, both of which land in Chunk 4. Rendering a fake
// grid here would mislead the operator into reading "load" off
// invented cells. So this card carries a centred "needs Chunk 4"
// message instead.
export default function ProductionLoadPlaceholder() {
  return (
    <div className="rounded-2xl border border-slate-800 bg-card p-5 shadow-sm shadow-black/20 backdrop-blur-sm flex flex-col">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-100">
            Production Load
          </h3>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Day × Category capacity heatmap
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
            <Factory size={18} strokeWidth={1.75} />
          </span>
          <div className="text-sm font-display text-slate-300">
            Production capacity
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-1">
            Needs Chunk 4
          </div>
          <div className="text-xs text-slate-600 mt-3 leading-relaxed">
            Capacity per recipe category isn't tracked yet. No fake cells —
            wired in when the data lands.
          </div>
        </div>
      </div>
    </div>
  );
}
