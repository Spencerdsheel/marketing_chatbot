"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  BookOpen,
  Building2,
  LayoutDashboard,
  LogOut,
  Settings2,
  UsersRound,
} from "lucide-react";
import type { Role } from "@/lib/auth";
import { cn } from "@/lib/utils";

interface AdminShellProps {
  children: React.ReactNode;
  role: Role;
  identityLabel: string;
  logoutAction: () => Promise<void>;
}

interface NavItem {
  href: string;
  label: string;
  mobileLabel?: string;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  roles: Role[];
}

const navigation: NavItem[] = [
  {
    href: "/",
    label: "Dashboard",
    icon: LayoutDashboard,
    roles: ["CLIENT_ADMIN", "CLIENT_AGENT"],
  },
  { href: "/leads", label: "Leads", icon: UsersRound, roles: ["CLIENT_ADMIN", "CLIENT_AGENT"] },
  {
    href: "/knowledge",
    label: "Knowledge base",
    mobileLabel: "Knowledge",
    icon: BookOpen,
    roles: ["CLIENT_ADMIN"],
  },
  {
    href: "/analytics",
    label: "Analytics",
    icon: BarChart3,
    roles: ["CLIENT_ADMIN", "CLIENT_AGENT"],
  },
  {
    href: "/settings",
    label: "Bot settings",
    icon: Settings2,
    roles: ["CLIENT_ADMIN", "CLIENT_AGENT"],
  },
  {
    href: "/clients",
    label: "Clients",
    icon: Building2,
    roles: ["PLATFORM_ADMIN"],
  },
];

function isCurrentPath(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`);
}

export function AdminShell({ children, role, identityLabel, logoutAction }: AdminShellProps) {
  const pathname = usePathname();
  const visibleItems = navigation.filter((item) => item.roles.includes(role));
  const isPlatformAdmin = role === "PLATFORM_ADMIN";

  return (
    <div className="flex min-h-screen bg-[#fbfbf8] text-[#191a17]">
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 flex-col border-r border-[#e7e7e2] bg-[#f7f7f3] px-3.5 py-4 lg:flex">
        <div className="flex items-center gap-2.5 px-2 pb-6">
          <div className="grid size-[34px] place-items-center rounded-[10px] bg-[#191a17] text-xs font-bold text-[#e4f222]">
            CL
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold tracking-[-0.02em]">ChatLeads</p>
            <p className="truncate text-[11px] text-[#96978e]">
              {isPlatformAdmin ? "Platform workspace" : "Client workspace"}
            </p>
          </div>
        </div>

        <p className="px-2 py-1 text-[10px] font-semibold tracking-[0.08em] text-[#a8a99f] uppercase">
          {isPlatformAdmin ? "Platform" : "Overview"}
        </p>
        <nav aria-label="Main navigation" className="mt-1 flex flex-col gap-1">
          {visibleItems.map((item) => {
            const Icon = item.icon;
            const current = isCurrentPath(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 text-[13px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]",
                  current
                    ? "bg-[#ecece5] font-semibold text-[#191a17]"
                    : "text-[#45463f] hover:bg-[#ecece5]/70"
                )}
              >
                <Icon aria-hidden className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto border-t border-[#e7e7e2] pt-3">
          <div className="flex items-center gap-2.5 px-2 py-2">
            <div className="grid size-8 shrink-0 place-items-center rounded-full bg-[#dcdcd2] text-[10px] font-bold text-[#5a5b54]">
              {identityLabel.slice(0, 2).toUpperCase()}
            </div>
            <p className="min-w-0 truncate text-xs font-semibold">{identityLabel}</p>
          </div>
          <form action={logoutAction}>
            <button
              type="submit"
              className="flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-[#5a5b54] transition-colors hover:bg-[#ecece5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]"
            >
              <LogOut aria-hidden className="size-4" />
              Log out
            </button>
          </form>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex min-h-16 items-center border-b border-[#e7e7e2] bg-[#fbfbf8] px-4 lg:hidden">
          <Link href="/" className="flex items-center gap-2 text-sm font-bold">
            <span className="grid size-8 place-items-center rounded-lg bg-[#191a17] text-[10px] text-[#e4f222]">
              CL
            </span>
            ChatLeads
          </Link>
          <form action={logoutAction} className="ml-auto">
            <button
              type="submit"
              aria-label="Log out"
              className="grid size-11 place-items-center rounded-lg text-[#45463f] transition-colors hover:bg-[#ecece5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#191a17]"
            >
              <LogOut aria-hidden className="size-4" />
            </button>
          </form>
        </header>
        <div className="flex min-w-0 flex-1 flex-col pb-20 lg:pb-0">{children}</div>
        <nav
          aria-label="Mobile navigation"
          className={cn(
            "fixed inset-x-0 bottom-0 z-40 grid min-h-16 border-t border-[#e7e7e2] bg-[#fbfbf8]/95 px-2 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden",
            visibleItems.length === 1
              ? "grid-cols-1"
              : visibleItems.length === 4
                ? "grid-cols-4"
                : "grid-cols-5"
          )}
        >
          {visibleItems.map((item) => {
            const Icon = item.icon;
            const current = isCurrentPath(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-label={item.label}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "flex min-h-14 min-w-0 flex-col items-center justify-center gap-1 rounded-lg px-1 text-[10px] transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-[#191a17]",
                  current ? "bg-[#ecece5] font-semibold" : "hover:bg-[#ecece5]/70"
                )}
              >
                <Icon aria-hidden className="size-4" />
                <span className="max-w-full truncate">{item.mobileLabel ?? item.label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </div>
  );
}
