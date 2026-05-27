import { createPortal } from "react-dom";
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
  ChevronRight,
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
const ASIDE_STYLE = {
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
  background: "#050912",
  borderRight: "1px solid rgb(30 41 59)",
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
  return createPortal(
    <aside style={ASIDE_STYLE}>
      <div style={HEADER_STYLE} className="px-5 py-5 border-b border-slate-800">
        <div className="font-display text-xl font-bold tracking-tight text-slate-100">
          STOCK.UP
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-brand mt-1 font-medium">
          BAKERY
        </div>
      </div>
      <nav style={NAV_STYLE} className="px-3 py-3 space-y-1">
        {NAV.map(({ label, icon: Icon, href }) => {
          const active = path === href || path.startsWith(href);
          return (
          <a
            key={label}
            href={href}
            className={
              "relative flex items-center gap-3 pl-4 pr-3 py-2 rounded-lg text-sm font-display transition " +
              (active
                ? "bg-brand/15 text-brand"
                : "text-slate-400 hover:bg-slate-900 hover:text-slate-100")
            }
          >
            {active && (
              <span
                aria-hidden="true"
                className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r bg-brand"
              />
            )}
            <Icon size={16} strokeWidth={1.75} />
            <span className="flex-1">{label}</span>
          </a>
        );})}
      </nav>
      <div style={FOOTER_STYLE} className="border-t border-slate-800 p-3 space-y-2">
        <div className="flex items-center justify-between px-3 py-2 rounded-lg text-sm text-slate-300">
          <span className="flex items-center gap-3">
            <Moon size={15} strokeWidth={1.75} />
            Dark mode
          </span>
          <button
            type="button"
            className="relative inline-flex h-5 w-9 items-center rounded-full bg-brand transition"
            title="Light mode not wired yet"
            aria-label="Toggle theme (light mode coming soon)"
          >
            <span
              aria-hidden="true"
              className="inline-block h-3.5 w-3.5 rounded-full bg-white shadow translate-x-[18px] transition-transform"
            />
          </button>
        </div>
        <a
          href="/logout/"
          className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-slate-900 transition"
        >
          <div className="h-9 w-9 shrink-0 rounded-full bg-brand text-page flex items-center justify-center font-display text-sm font-bold">
            B
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm text-slate-100 font-display leading-tight truncate">
              Bakery account
            </div>
            <div className="text-[10px] text-slate-500 font-mono uppercase tracking-widest truncate mt-0.5">
              Sign out
            </div>
          </div>
          <ChevronRight size={13} strokeWidth={1.75} className="text-slate-500 shrink-0" />
        </a>
      </div>
    </aside>,
    document.body,
  );
}
