import { createPortal } from "react-dom";
import { useEffect, useState } from "react";
import {
  LayoutDashboard,
  ScrollText,
  LineChart,
  BarChart3,
  Package,
  ChefHat,
  Boxes,
  Truck,
  Users,
  Moon,
  Sun,
  LogOut,
} from "lucide-react";

// Fixed left rail. Every entry routes to a page that actually exists
// in the Django app — no nav that 404s. Active item is hard-coded to
// Dashboard (client router lands later; for now /dashboard is the only
// SPA route).
const NAV = [
  { label: "Dashboard",  icon: LayoutDashboard, href: "/dashboard/" },
  { label: "Business Performance", icon: BarChart3, href: "/business-performance-dashboard/" },
  { label: "Orders",     icon: ScrollText,      href: "/orders/" },
  { label: "Financials", icon: LineChart,       href: "/financials/" },
  { label: "Products",   icon: Package,         href: "/products/" },
  { label: "Recipes",    icon: ChefHat,         href: "/recipes/" },
  { label: "Stock",      icon: Boxes,           href: "/stock/" },
  { label: "Deliveries", icon: Truck,           href: "/deliveries/" },
  { label: "Customers",  icon: Users,           href: "/customers/" },
];

// Every layout-critical property is inlined so Tailwind purge, CSS
// cascade order, or any future global rule can't silently break the
// rail's positioning. Previous attempt used `bottom:0 + height:100vh`
// together — this drops `bottom` to avoid any chance of the browser
// preferring the bottom anchor. The footer block uses an inline
// `marginTop:auto` to bottom-pin itself rather than relying on
// `flex-1` on the nav.
const BASE_ASIDE_STYLE = {
  position: "fixed",
  top: 0,
  left: 0,
  width: "16rem",
  height: "100vh",
  zIndex: 50,
  display: "flex",
  flexDirection: "column",
  alignItems: "stretch",
  justifyContent: "flex-start",
  overflow: "hidden",
  boxSizing: "border-box",
};

const HEADER_STYLE = { flex: "0 0 auto" };
const NAV_STYLE    = { flex: "1 1 auto", overflowY: "auto", minHeight: 0 };
const FOOTER_STYLE = { flex: "0 0 auto", marginTop: "auto" };

// Rendered via createPortal into document.body so the aside is a
// direct child of <body> at the DOM level. With position:fixed +
// top:0, this guarantees the rail anchors to the viewport regardless
// of any React-managed wrapper above (a transformed/filtered/contained
// ancestor would otherwise become the containing block per CSS spec
// and produce exactly the "sidebar at bottom-left" symptom we hit).
export default function Sidebar() {
  if (typeof document === "undefined") return null;  // SSR safety; harmless here
  const path = window.location.pathname;
  const [dark, setDark] = useState(() => {
    const saved = window.localStorage.getItem("stockup-theme");
    if (saved) return saved === "dark";
    return document.documentElement.classList.contains("dark");
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    window.localStorage.setItem("stockup-theme", dark ? "dark" : "light");
  }, [dark]);

  const asideStyle = {
    ...BASE_ASIDE_STYLE,
    background: dark ? "#020617" : "#ffffff",
    borderRight: dark ? "1px solid rgb(30 41 59)" : "1px solid rgb(226 232 240)",
  };

  return createPortal(
    <aside style={asideStyle}>
      <div style={HEADER_STYLE} className="border-b border-slate-200 px-5 py-5 dark:border-slate-800">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-slate-950 font-display text-sm font-semibold text-white dark:bg-white dark:text-slate-950">
            SU
          </div>
          <div>
            <div className="font-display text-lg font-semibold tracking-normal text-slate-950 dark:text-slate-100">
              StockUp
            </div>
            <div className="mt-0.5 text-xs font-semibold uppercase tracking-[0.18em] text-amber-700 dark:text-amber-300">
              Bakery
            </div>
          </div>
        </div>
      </div>
      <nav style={NAV_STYLE} className="space-y-1 px-3 py-4">
        {NAV.map(({ label, icon: Icon, href }) => {
          const active = path === href || path.startsWith(href);
          return (
          <a
            key={label}
            href={href}
            className={
              "relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition " +
              (active
                ? "bg-amber-50 text-slate-950 ring-1 ring-amber-200 dark:bg-slate-900 dark:text-slate-100 dark:ring-slate-700"
                : "text-slate-500 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-400 dark:hover:bg-slate-900 dark:hover:text-slate-100")
            }
          >
            {active && (
              <span
                aria-hidden="true"
                className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r bg-amber-500"
              />
            )}
            <Icon size={16} strokeWidth={1.75} />
            <span className="flex-1">{label}</span>
          </a>
        );})}
      </nav>
      <div style={FOOTER_STYLE} className="space-y-2 border-t border-slate-200 p-3 dark:border-slate-800">
        <div className="flex items-center justify-between rounded-lg px-3 py-2 text-sm text-slate-600 dark:text-slate-300">
          <span className="flex items-center gap-3">
            {dark ? <Sun size={15} strokeWidth={1.75} /> : <Moon size={15} strokeWidth={1.75} />}
            Dark mode
          </span>
          <button
            type="button"
            onClick={() => setDark((v) => !v)}
            className={
              "relative inline-flex h-5 w-9 items-center rounded-full transition " +
              (dark ? "bg-amber-500" : "bg-slate-200")
            }
            title={dark ? "Switch to light mode" : "Switch to dark mode"}
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
            aria-pressed={dark}
          >
            <span
              aria-hidden="true"
              className={
                "inline-block h-3.5 w-3.5 rounded-full bg-white shadow transition-transform " +
                (dark ? "translate-x-[18px]" : "translate-x-1")
              }
            />
          </button>
        </div>
        <a
          href="/logout/"
          className="flex items-center gap-3 rounded-lg px-3 py-2 transition hover:bg-slate-100 dark:hover:bg-slate-900"
        >
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-100 font-display text-sm font-bold text-amber-800 dark:bg-amber-400/15 dark:text-amber-200">
            B
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate font-display text-sm leading-tight text-slate-950 dark:text-slate-100">
              Bakery account
            </div>
            <div className="mt-0.5 truncate text-xs text-slate-500 dark:text-slate-400">
              Sign out
            </div>
          </div>
          <LogOut size={14} strokeWidth={1.75} className="shrink-0 text-slate-400" />
        </a>
      </div>
    </aside>,
    document.body,
  );
}
