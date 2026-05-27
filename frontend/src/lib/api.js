// Same-origin fetch. SessionAuthentication + IsAuthenticated on the
// Django side; the browser already carries the session cookie so we
// just need credentials:"same-origin" to be explicit about it.
async function getJson(url) {
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (res.status === 401 || res.status === 403) {
    window.location.assign(
      `/login/?next=${encodeURIComponent(window.location.pathname)}`,
    );
    throw new Error("unauthenticated");
  }
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}

// Single-week dashboard payload. Empty/missing week defaults to latest
// imported week on the server side, so `fetchWeekSummary()` (no arg) is
// the "give me the freshest" call.
export function fetchWeekSummary(week) {
  const qs = week ? `?week=${encodeURIComponent(week)}` : "?week=";
  return getJson(`/api/dashboard/summary/${qs}`);
}

// Direct download URL for the week CSV. Used as an <a href> so the
// browser handles the file save dialog itself.
export function exportCsvUrl(week) {
  return week
    ? `/api/dashboard/export.csv?week=${encodeURIComponent(week)}`
    : "/api/dashboard/export.csv";
}

// Multi-week Business Performance payload. Both from/to are optional;
// the server defaults to "last 8 imported weeks" and clamps any out-
// of-range value to the available_weeks span. Both are Monday-snapped
// (any day inside a week resolves to that week's Monday).
export function fetchBusinessPerformance({ from, to } = {}) {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const qs = params.toString();
  return getJson(
    `/api/business-performance/summary/${qs ? `?${qs}` : ""}`,
  );
}
