import { weekLongLabel } from "../lib/format.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function BPProductDayHeatmap({
  rows,
  weekStart,
  mode = "day",
  buckets = [],
  granularity = "week",
}) {
  const isBucketMode = mode === "bucket";
  const columns = isBucketMode
    ? bucketColumns(buckets, granularity)
    : dayColumns(weekStart);
  const columnCount = columns.length || (isBucketMode ? 0 : 7);
  const data = (rows || []).slice(0, 8).map((row) => ({
    ...row,
    series: normaliseSeries(
      isBucketMode ? row.values : row.daily,
      columnCount,
    ),
  }));
  const maxQty = Math.max(
    0,
    ...data.flatMap((r) => r.series.map((q) => Number(q) || 0)),
  );
  const title = isBucketMode
    ? `Ordered by Product × ${granularity === "month" ? "Month" : "Week"}`
    : "Ordered by Product × Day";
  const subtitle = isBucketMode
    ? "Ordered quantity · selected range · external customers"
    : "Ordered quantity · selected week · external customers";
  const emptyLabel = isBucketMode
    ? "No product demand for this range."
    : "No product demand for this selected week.";
  const productWidth = Math.max(24, Math.min(34, 44 - columnCount * 1.2));
  const totalWidth = 12;
  const cellWidth = columnCount
    ? (100 - productWidth - totalWidth) / columnCount
    : 0;

  return (
    <section className="w-full rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-display text-base font-semibold text-slate-950 dark:text-slate-100">
            {title}
          </h3>
          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            {subtitle}
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            document
              .getElementById("product-ordered-value")
              ?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          className="rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-950 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-slate-700 dark:hover:bg-slate-800 dark:hover:text-white"
        >
          View all products
        </button>
      </div>

      {data.length === 0 || columns.length === 0 ? (
        <div className="rounded-lg border border-dashed border-slate-200 px-3 py-4 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
          {emptyLabel}
        </div>
      ) : (
        <div className="w-full max-w-[1300px]">
          <table
            className="w-full table-fixed text-xs"
          >
            <colgroup>
              <col style={{ width: `${productWidth}%` }} />
              {columns.map((column) => (
                <col key={column.key} style={{ width: `${cellWidth}%` }} />
              ))}
              <col style={{ width: `${totalWidth}%` }} />
            </colgroup>
            <thead>
              <tr className="border-b border-slate-100 text-left font-semibold text-slate-500 dark:border-slate-800 dark:text-slate-400">
                <th className="py-1.5 pr-3">Product</th>
                {columns.map((column) => (
                  <th
                    key={column.key}
                    className="px-1 py-1.5 text-center"
                    title={column.tooltip}
                  >
                    {column.label}
                  </th>
                ))}
                <th className="py-1.5 pl-3 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr
                  key={row.product}
                  className="border-b border-slate-100 transition-colors last:border-0 hover:bg-slate-50/80 dark:border-slate-800 dark:hover:bg-slate-800/50"
                >
                  <td
                    className="max-w-[260px] truncate py-1.5 pr-3 font-medium text-slate-700 dark:text-slate-200"
                    title={row.product}
                  >
                    {row.product}
                  </td>
                  {row.series.map((qty, i) => (
                    <td key={`${row.product}-${columns[i].key}`} className="px-1 py-1">
                      <div
                        className="flex h-6 w-full items-center justify-center rounded tabular text-[10px] font-semibold text-slate-950 ring-1 ring-inset ring-amber-900/5 dark:text-slate-100 sm:text-[11px]"
                        style={heatCellStyle(qty, maxQty)}
                        title={`${row.product} · ${columns[i].tooltip} · ordered quantity: ${formatQty(qty) || "0"}`}
                      >
                        {formatQty(qty)}
                      </div>
                    </td>
                  ))}
                  <td className="py-1.5 pl-3 text-right tabular font-semibold text-slate-700 dark:text-slate-200">
                    {formatQty(Number(row.total_qty))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function dayColumns(weekStart) {
  return DAYS.map((day, i) => ({
    key: day,
    label: day,
    tooltip: dayTooltip(weekStart, i),
  }));
}

function bucketColumns(buckets, granularity) {
  const years = new Set(
    (buckets || []).map((iso) => new Date(`${iso}T00:00:00Z`).getUTCFullYear()),
  );
  return (buckets || []).map((iso) => ({
    key: iso,
    label: granularity === "month"
      ? monthShortLabel(iso, years.size > 1)
      : weekShortLabel(iso),
    tooltip: granularity === "month"
      ? monthTooltip(iso)
      : `w/c ${weekLongLabel(iso)}`,
  }));
}

function normaliseSeries(series, count) {
  const values = (series || []).slice(0, count).map((q) => Number(q) || 0);
  while (values.length < count) values.push(0);
  return values;
}

function heatCellStyle(qty, maxQty) {
  if (qty <= 0 || maxQty <= 0) {
    return { background: "rgba(148, 163, 184, 0.08)", color: "transparent" };
  }
  const ratio = Math.max(0.12, qty / maxQty);
  return {
    background: `rgba(245, 164, 0, ${Math.min(0.9, ratio).toFixed(3)})`,
  };
}

function dayTooltip(weekStart, offset) {
  if (!weekStart) return DAYS[offset];
  const d = new Date(`${weekStart}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + offset);
  return `${DAYS[offset]} ${weekLongLabel(d.toISOString().slice(0, 10))}`;
}

function weekShortLabel(iso) {
  if (!iso) return "--";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "2-digit",
    timeZone: "UTC",
  });
}

function monthShortLabel(iso, includeYear) {
  if (!iso) return "--";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    month: "short",
    year: includeYear ? "2-digit" : undefined,
    timeZone: "UTC",
  });
}

function monthTooltip(iso) {
  if (!iso) return "--";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

function formatQty(value) {
  const n = Number(value);
  if (!Number.isFinite(n) || n === 0) return "";
  if (Number.isInteger(n)) return n.toString();
  return n.toFixed(3).replace(/\.?0+$/, "");
}
