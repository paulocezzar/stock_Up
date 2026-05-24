import { Lock } from "lucide-react";

// Disabled placeholder. Production-load needs product categories +
// capacity (Chunk 4). The dashboard rule is "no fabricated grids that
// look real" — so this renders a single panel that openly admits it's
// not wired up. When Chunk 4 lands, replace the body with the real
// heatmap; keep the same panel chrome.
export default function ProductionHeatmap() {
  return (
    <div className="rounded-xl border border-slate-800 bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="font-display text-sm font-semibold text-slate-100">
            Production Load
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-0.5">
            Day × Category heatmap
          </div>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-widest text-slate-600 flex items-center gap-1.5">
          <Lock size={11} strokeWidth={1.5} />
          Coming soon
        </span>
      </div>
      <div className="h-40 rounded-md border border-dashed border-slate-800 flex items-center justify-center px-4">
        <div className="text-center">
          <div className="text-xs text-slate-500">
            Needs product categories + capacity (Chunk 4).
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-slate-600 mt-1">
            No fabricated grid — wired in when the data lands.
          </div>
        </div>
      </div>
    </div>
  );
}
