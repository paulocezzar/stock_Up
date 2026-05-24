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
