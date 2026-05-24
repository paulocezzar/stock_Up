import {
  LayoutDashboard,
  Package,
  ChefHat,
  Boxes,
  Truck,
  Users,
  ScrollText,
  LineChart,
  Settings,
} from "lucide-react";

// Phase A: visual shell only. Items link out to the existing Django
// pages — the React app is a sibling of Orders / Financials etc., not
// a replacement. The active item is hard-coded to Dashboard for now;
// router lives in Phase B.
const NAV = [
  { label: "Dashboard", icon: LayoutDashboard, href: "/dashboard", active: true },
  { label: "Orders", icon: ScrollText, href: "/orders/" },
  { label: "Financials", icon: LineChart, href: "/financials/" },
  { label: "Products", icon: Package, href: "/products/" },
  { label: "Recipes", icon: ChefHat, href: "/recipes/" },
  { label: "Stock", icon: Boxes, href: "/stock/" },
  { label: "Deliveries", icon: Truck, href: "/deliveries/" },
  { label: "Customers", icon: Users, href: "/customers/" },
];

export default function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-56 lg:w-60 shrink-0 flex-col border-r border-slate-800 bg-slate-950/60">
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="font-display text-amber-400 text-lg font-bold tracking-tight">
          STOCK.UP
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-slate-500 mt-1">
          Bakery dashboard
        </div>
      </div>
      <nav className="flex-1 py-3">
        {NAV.map(({ label, icon: Icon, href, active }) => (
          <a
            key={label}
            href={href}
            className={
              "flex items-center gap-3 px-5 py-2.5 text-sm font-display " +
              (active
                ? "bg-amber-400/10 text-amber-400 border-l-2 border-amber-400"
                : "text-slate-300 hover:bg-slate-900/60 hover:text-slate-100 border-l-2 border-transparent")
            }
          >
            <Icon size={16} strokeWidth={1.5} />
            {label}
          </a>
        ))}
      </nav>
      <div className="border-t border-slate-800 px-5 py-3">
        <a
          href="/profile/"
          className="flex items-center gap-3 text-sm text-slate-400 hover:text-slate-200"
        >
          <Settings size={16} strokeWidth={1.5} />
          Profile
        </a>
      </div>
    </aside>
  );
}
