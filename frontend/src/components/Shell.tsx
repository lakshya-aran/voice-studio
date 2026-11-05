import { FolderOpen, LayoutGrid, LogOut, ShieldCheck, UsersRound } from "lucide-react";
import { NavLink, Outlet } from "react-router";
import { useAuth } from "../auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutGrid, end: true },
  { to: "/voices", label: "Voice library", icon: UsersRound },
  { to: "/projects", label: "Projects", icon: FolderOpen },
  { to: "/activity", label: "Activity log", icon: ShieldCheck },
];

export function Logo() {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span className="flex items-center gap-[3px] h-5" aria-hidden>
        {[8, 18, 12, 5].map((h, i) => (
          <span key={i} className="w-[3px] rounded-full bg-signal" style={{ height: h }} />
        ))}
      </span>
      <span className="condensed text-[19px] font-semibold tracking-tight">Voice Studio</span>
    </span>
  );
}

export function Shell() {
  const { user, logout } = useAuth();
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[220px_1fr]">
      <aside className="md:sticky md:top-0 md:h-dvh border-b md:border-b-0 md:border-r border-line bg-well flex md:flex-col">
        <div className="px-5 h-14 md:h-16 flex items-center shrink-0">
          <Logo />
        </div>
        <nav className="flex md:flex-col gap-0.5 px-2 md:px-3 overflow-x-auto md:overflow-visible items-center md:items-stretch" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-control px-3 h-9 text-[14px] whitespace-nowrap transition-colors ${
                  isActive ? "bg-raised text-ink shadow-[inset_2px_0_0_var(--color-signal)]" : "text-ink-soft hover:text-ink"
                }`
              }
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className="hidden sm:inline">{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="md:mt-auto ml-auto md:ml-0 p-2 md:p-3 md:border-t border-line flex items-center gap-2 shrink-0">
          <div className="hidden md:block min-w-0 flex-1 px-1">
            <p className="text-[13px] truncate">{user?.name}</p>
            <p className="legend truncate">{user?.email}</p>
          </div>
          <button onClick={logout} className="inline-grid place-items-center size-8 rounded-control text-muted hover:text-ink hover:bg-raised" aria-label="Sign out" title="Sign out">
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>
      <main className="min-w-0">
        <Outlet />
      </main>
    </div>
  );
}

export function PageBody({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return <div className={`mx-auto px-4 sm:px-8 py-8 sm:py-10 ${wide ? "max-w-[1400px]" : "max-w-[1120px]"}`}>{children}</div>;
}

