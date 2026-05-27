import { CalendarRange, ChevronDown } from "lucide-react";
import { weekLongLabel } from "../lib/format.js";

// Date-range button in the header. Reads as a button (icon + current
// week label + chevron) but is actually a native <select> overlaid
// with opacity:0 so the OS-native dropdown opens on click. Options
// come from the API's `available_weeks` — only imported weeks are
// pickable.
export default function WeekPicker({ value, options, onChange }) {
  return (
    <div className="relative inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-800 bg-card hover:border-brand/40 transition">
      <CalendarRange size={14} strokeWidth={1.75} className="text-slate-400" />
      <span className="font-display text-xs text-slate-200">
        w/c {weekLongLabel(value)}
      </span>
      <ChevronDown size={12} strokeWidth={2} className="text-slate-500" />
      <select
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
        aria-label="Select week"
      >
        {(options || []).map((iso) => (
          <option key={iso} value={iso}>
            w/c {weekLongLabel(iso)}
          </option>
        ))}
      </select>
    </div>
  );
}
