import { NavLink } from "react-router-dom";

import { Logo } from "@/components/layout/Logo";
import { cn } from "@/lib/cn";

export interface NavItem {
  to: string;
  label: string;
  /** Раздел недоступен, пока проект не обработан. */
  disabled?: boolean;
  title?: string;
}

interface TopNavProps {
  items: NavItem[];
  projectLabel: string;
  status: { text: string; tone: "idle" | "running" | "ready" };
}

const TONES = {
  idle: "bg-ink-faint text-ink-muted",
  running: "bg-ok text-ok-ink",
  ready: "bg-ok text-ok-ink",
} as const;

export function TopNav({ items, projectLabel, status }: TopNavProps) {
  return (
    <header className="sticky top-0 z-[900] border-b border-line bg-white/95 backdrop-blur">
      <div className="flex h-[68px] items-center gap-10 px-7">
        <NavLink to="/" aria-label="AgroPulse — на главную">
          <Logo />
        </NavLink>

        <nav className="flex items-center gap-1">
          {items.map((item) =>
            item.disabled ? (
              <span
                key={item.to}
                title={item.title}
                className="cursor-not-allowed px-4 py-2 text-[15px] text-ink-faint"
              >
                {item.label}
              </span>
            ) : (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    "relative px-4 py-2 text-[15px] transition-colors",
                    isActive
                      ? "font-medium text-brand-700 after:absolute after:inset-x-3.5 after:-bottom-[15px] after:h-[2.5px] after:rounded-full after:bg-brand-700"
                      : "text-ink hover:text-brand-700",
                  )
                }
              >
                {item.label}
              </NavLink>
            ),
          )}
        </nav>

        <div className="ml-auto flex items-center gap-5">
          <span className="text-[15px] text-ink-soft">{projectLabel}</span>
          <span className="flex items-center gap-2 text-[14px] text-ink-muted">
            <span className={cn("h-2 w-2 rounded-full", TONES[status.tone].split(" ")[0])} />
            <span className={status.tone === "idle" ? "text-ink-muted" : "text-ok-ink"}>
              {status.text}
            </span>
          </span>
        </div>
      </div>
    </header>
  );
}
