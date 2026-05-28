// Currency / percent / date formatters. The API returns 2dp currency
// strings and 1dp percentage strings so the SPA reads exactly what the
// Django Financials page shows — no client-side rounding skew.

export function gbp(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency: "GBP",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
}

export function pct(value, { signed = false } = {}) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  const sign = signed && n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

export function weekLabel(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  });
}

export function weekLongLabel(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function weekRangeLabel(fromIso, toIso = fromIso) {
  if (!fromIso) return "—";
  const start = new Date(`${fromIso}T00:00:00Z`);
  const end = new Date(`${toIso || fromIso}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() + 6);
  return `${formatLongDate(start)} to ${formatLongDate(end)}`;
}

export function weekdayShort(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00Z`);
  return d.toLocaleDateString("en-GB", {
    weekday: "short",
    timeZone: "UTC",
  });
}

function formatLongDate(date) {
  return date.toLocaleDateString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
