import { createPortal } from "react-dom";
import {
  LayoutDashboard,
  ScrollText,
  LineChart,
  Package,
  ChefHat,
  Boxes,
  Truck,
  Users,
  Moon,
  LogOut,
} from "lucide-react";

// Fixed left rail. Every entry routes to a page that actually exists
// in the Django app — no nav that 404s. Active item is hard-coded to
// Dashboard (client router lands later; for now /dashboard is the only
// SPA route).
const NAV = [
  { label: "Dashboard",  icon: LayoutDashboard, href: "/dashboard/",   active: true },
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
  return createPortal(
    <aside style={ASIDE_STYLE}>
      <div style={HEADER_STYLE} className="px-5 py-5 border-b border-slate-800">
        <div className="font-display text-xl font-bold tracking-tight text-slate-100">
          STOCK.UP
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-brand mt-1">
          Bakery
        </div>
      </div>
      <nav style={NAV_STYLE} className="px-3 py-3 space-y-1">
        {NAV.map(({ label, icon: Icon, href, active }) => (
          <a
            key={label}
            href={href}
            className={
              "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-display transition " +
              (active
                ? "bg-brand/15 text-brand"
                : "text-slate-400 hover:bg-slate-900 hover:text-slate-100")
            }
          >
            <Icon size={16} strokeWidth={1.75} />
            <span className="flex-1">{label}</span>
          </a>
        ))}
      </nav>
      <div style={FOOTER_STYLE} className="border-t border-slate-800 p-3 space-y-2">
        <button
          type="button"
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-400 hover:bg-slate-900 hover:text-slate-100 transition"
          title="Light mode not wired yet"
        >
          <Moon size={15} strokeWidth={1.75} />
          <span className="flex-1 text-left">Dark</span>
        </button>
        <a
          href="/logout/"
          className="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-slate-400 hover:bg-slate-900 hover:text-slate-100 transition"
        >
          <div className="h-7 w-7 rounded-full bg-brand/15 text-brand flex items-center justify-center font-display text-xs">
            B
          </div>
          <span className="flex-1 truncate">Bakery account</span>
          <LogOut size={13} strokeWidth={1.75} />
        </a>
      </div>
    </aside>,
    document.body,
  );
}
