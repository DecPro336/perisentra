"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { Activity, BadgeDollarSign, BookCheck, Boxes, ChartNoAxesCombined, Database, FlaskConical, Gauge, Menu, Moon, ScrollText, Sun, X, Thermometer } from "lucide-react";
import { useTheme } from "@/lib/theme";
import { useI18n } from "@/lib/i18n";
import { useMeta } from "@/lib/api";
import { longDate } from "@/lib/format";
import { cn } from "@/lib/utils";

const NAV = [
  { section: "nav.section.operate", items: [
    { href: "/", key: "nav.overview", icon: Gauge },
    { href: "/recommendations", key: "nav.recommendations", icon: BookCheck },
    { href: "/risk", key: "nav.risk", icon: Thermometer },
  ] },
  { section: "nav.section.understand", items: [
    { href: "/elasticity", key: "nav.elasticity", icon: BadgeDollarSign },
    { href: "/validation", key: "nav.validation", icon: FlaskConical },
    { href: "/models", key: "nav.models", icon: ChartNoAxesCombined },
  ] },
  { section: "nav.section.govern", items: [
    { href: "/monitoring", key: "nav.monitoring", icon: Activity },
    { href: "/data", key: "nav.data", icon: Database },
    { href: "/rules", key: "nav.rules", icon: ScrollText },
  ] },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand">
        <svg viewBox="0 0 32 32" className="h-6 w-6"><path d="M9 21c4-1 7-4 8-9 2 3 3 7 1 10-2 2-6 2-9-1z" fill="var(--brand-soft)" /><circle cx="21.5" cy="10.5" r="2.5" fill="#fab219" /></svg>
      </div>
      <div className="leading-tight">
        <div className="text-[15px] font-semibold tracking-tight text-ink">Perisentra</div>
        <div className="text-[11.5px] text-ink-3">Fresh decision engine</div>
      </div>
    </div>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const path = usePathname();
  const { t } = useI18n();
  return (
    <nav className="mt-6 space-y-5">
      {NAV.map((g) => (
        <div key={g.section}>
          <div className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">{t(g.section)}</div>
          <ul className="space-y-0.5">
            {g.items.map(({ href, key, icon: Icon }) => {
              const active = href === "/" ? path === "/" : path.startsWith(href) || (href === "/recommendations" && path.startsWith("/item"));
              return (
                <li key={href}>
                  <Link href={href} onClick={onNavigate} className={cn("flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors",
                    active ? "bg-brand-soft text-brand" : "text-ink-2 hover:bg-surface-2 hover:text-ink")}>
                    <Icon className="h-4 w-4" />
                    {t(key)}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function TopBar({ onMenu }: { onMenu: () => void }) {
  const { t, lang } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  const { data: meta } = useMeta();
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-page/85 px-4 backdrop-blur md:px-8">
      <button className="md:hidden" onClick={onMenu} aria-label="Open menu"><Menu className="h-5 w-5" /></button>
      <div className="flex min-w-0 items-center gap-2 text-[13px]">
        <Boxes className="hidden h-4 w-4 text-ink-3 sm:block" />
        <span className="hidden font-medium text-ink sm:inline">{meta?.chain_name ?? "…"}</span>
        <span className="hidden text-ink-3 sm:inline">·</span>
        <span className="truncate text-ink-2">{t("top.asof")} <span className="font-medium text-ink">{meta?.as_of_date ? longDate(meta.as_of_date, lang) : "…"}</span></span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <button onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")} aria-label="Toggle theme"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border bg-surface text-ink-2 hover:text-ink">
          {resolvedTheme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </div>
    </header>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-[248px] shrink-0 overflow-y-auto border-r border-border bg-surface px-3 py-5 md:block">
        <Logo />
        <Nav />
        <SidebarFooter />
      </aside>
      {open && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-[260px] overflow-y-auto bg-surface px-3 py-5">
            <div className="flex items-center justify-between"><Logo /><button onClick={() => setOpen(false)} aria-label="Close menu"><X className="h-5 w-5" /></button></div>
            <Nav onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar onMenu={() => setOpen(true)} />
        <main className="mx-auto w-full max-w-[1480px] flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}

function SidebarFooter() {
  const { data: meta } = useMeta();
  if (!meta?.run_id) return null;   // nothing to show before the first scoring run
  return (
    <div className="mt-8 rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-[11.5px] leading-relaxed text-ink-3">
      <div className="font-medium text-ink-2">Champion models</div>
      <div className="truncate" title={meta.demand_model}>{meta.demand_model}</div>
      <div className="truncate" title={meta.elasticity_model}>{meta.elasticity_model}</div>
      <div>Rules v{(meta.rules_versions ?? [meta.rules_version]).join(", v")} · {meta.n_paths} MC paths</div>
    </div>
  );
}
