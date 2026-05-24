// Same-origin fetch. SessionAuthentication + IsAuthenticated on the
// Django side; the browser already carries the session cookie so we
// just need credentials:"same-origin" to be explicit about it.
export async function fetchDashboardSummary({ from, to } = {}) {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  const qs = params.toString();
  const url = `/api/dashboard/summary/${qs ? `?${qs}` : ""}`;
  const res = await fetch(url, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (res.status === 401 || res.status === 403) {
    // Anonymous user — bounce to the existing Django login page.
    window.location.assign(`/login/?next=${encodeURIComponent(window.location.pathname)}`);
    throw new Error("unauthenticated");
  }
  if (!res.ok) throw new Error(`API ${res.status}`);
  return res.json();
}
