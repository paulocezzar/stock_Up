import { weekLongLabel } from "../lib/format.js";

// Native <select> over the API's `available_weeks` list so the operator
// can jump straight to any imported week. Defaults to the currently-
// selected week (`value`). No client-side fabrication of weeks — only
// imported weeks are pickable.
export default function WeekPicker({ value, options, onChange }) {
  return (
    <label className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-slate-500">
      Week
      <select
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        className="bg-card border border-slate-800 rounded-md px-2 py-1 font-mono text-xs text-slate-200 focus:outline-none focus:border-brand"
      >
        {(options || []).map((iso) => (
          <option key={iso} value={iso}>
            w/c {weekLongLabel(iso)}
          </option>
        ))}
      </select>
    </label>
  );
}
