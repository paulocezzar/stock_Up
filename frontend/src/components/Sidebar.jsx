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

export default function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-64 flex flex-col border-r border-slate-800 bg-rail z-20">
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="font-display text-xl font-bold tracking-tight text-slate-100">
          STOCK.UP
        </div>
        <div className="font-mono text-[10px] uppercase tracking-widest text-brand mt-1">
          Bakery
        </div>
      </div>
      <nav className="flex-1 px-3 py-3 space-y-1 overflow-y-auto">
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
      <div className="border-t border-slate-800 p-3 space-y-2">
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
    </aside>
  );
}
