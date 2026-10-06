"use client";

import { isNotReady } from "@/lib/api";

import { useSyncExternalStore, type ComponentProps, type ReactNode } from "react";
import type { EChartsOption } from "echarts";
import { CircleAlert, CircleCheck, Hourglass, Minus, OctagonAlert, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import type { Lang } from "@/lib/format";
import { EChart, axisStyle, baseOption, type Tokens } from "@/components/charts/echart";

/** Shared helpers for the Validation, Models and Monitoring pages. */

export function is503(error: unknown) {
  return isNotReady(error) || String((error as Error)?.message ?? "").startsWith("503");
}

/**
 * baseOption with the page's resolved font family. ECharts measures label widths on a canvas, which cannot
 * resolve `var(--font-inter)`; without a concrete family, long axis labels are measured too narrow and clipped.
 */
const pageFont = () => (typeof document !== "undefined" ? getComputedStyle(document.body).fontFamily : undefined);

export function chartBase(t: Tokens): EChartsOption {
  const base = baseOption(t);
  const family = pageFont();
  return family ? { ...base, textStyle: { ...(base.textStyle as object), fontFamily: family } } : base;
}

/** axisStyle with the resolved font set on the labels themselves (axis-label layout ignores the global textStyle),
 *  and overlapping tick labels hidden on narrow screens. */
export function axisFont(t: Tokens) {
  const a = axisStyle(t);
  const family = pageFont();
  return { ...a, axisLabel: { ...a.axisLabel, hideOverlap: true, ...(family ? { fontFamily: family } : {}) } };
}

/* Latches once the page's web fonts have loaded (a later font load must not unmount charts). */
let fontsLoaded = false;
const fontsSnapshot = () => (fontsLoaded ||= !document.fonts || document.fonts.status === "loaded");
function subscribeFonts(cb: () => void) {
  let alive = true;
  document.fonts?.ready.then(() => { fontsLoaded = true; if (alive) cb(); });
  return () => { alive = false; };
}

/** True once web fonts have loaded, so ECharts measures axis labels with the real font (not a fallback). */
function useFontsReady() {
  return useSyncExternalStore(subscribeFonts, fontsSnapshot, () => false);
}

/** EChart that waits for fonts, keeping its height meanwhile (no layout jump). */
export function Chart(props: ComponentProps<typeof EChart>) {
  const ready = useFontsReady();
  return ready ? <EChart {...props} /> : <div aria-busy="true" style={{ height: props.height ?? 260 }} />;
}

/** Friendly "this artefact has not been produced yet" card, with the CLI command that produces it. */
export function NotReady({ title, children, command, compact }: { title: ReactNode; children?: ReactNode; command: string; compact?: boolean }) {
  const body = (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-surface-2 text-ink-3"><Hourglass className="h-5 w-5" /></div>
      <div className="max-w-md text-[13.5px] text-ink-2">{children}</div>
      <code className="rounded-md border border-border bg-surface-2 px-2.5 py-1 font-mono text-[12.5px] text-ink">{command}</code>
    </div>
  );
  if (compact) return body;
  return (
    <Card>
      <CardHeader title={title} />
      <CardBody>{body}</CardBody>
    </Card>
  );
}

type Level = "good" | "warning" | "serious" | "critical" | "neutral";
const ICONS = { good: CircleCheck, warning: TriangleAlert, serious: CircleAlert, critical: OctagonAlert, neutral: Minus };

/** Status badge: always icon + text, status colours only. */
export function StatusBadge({ level, children }: { level: Level; children: ReactNode }) {
  const Icon = ICONS[level];
  return <Badge variant={level} icon={<Icon className="h-3 w-3" />}>{children}</Badge>;
}

/** Colour swatch + label legend (HTML) shared by small multiples. Text stays in ink colours. */
export function SwatchLegend({ items }: { items: { label: string; color: string; shape?: "line" | "dot" | "diamond" | "block" }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-ink-2">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          {i.shape === "dot" ? <span className="h-2.5 w-2.5 rounded-full" style={{ background: i.color }} />
            : i.shape === "diamond" ? <span className="h-2 w-2 rotate-45" style={{ background: i.color }} />
            : i.shape === "block" ? <span className="h-3 w-3 rounded-[3px] border border-border-strong" style={{ background: i.color }} />
            : <span className="h-[3px] w-3 rounded-full" style={{ background: i.color }} />}
          {i.label}
        </span>
      ))}
    </div>
  );
}

/** Forecasting methods compared in the backtest. Colour follows the method everywhere. */
export const METHODS = ["model", "legacy", "seasonal_naive", "ma28"] as const;
export type Method = (typeof METHODS)[number];
export const METHOD_TOKEN: Record<Method, string> = { model: "series-1", legacy: "series-2", seasonal_naive: "series-3", ma28: "series-4" };
export function methodLabel(m: Method) {
  return {
    model: "Perisentra",
    legacy: "Current rule",
    seasonal_naive: "Seasonal naive (D-7)",
    ma28: "28-day average",
  }[m];
}

/** Tooltip row: colour swatch + label + value (value in ink, never the series colour). */
export function tipRow(color: string, label: string, value: string, inkMuted: string) {
  return `<div style="display:flex;align-items:center;gap:8px;justify-content:space-between;min-width:180px">`
    + `<span style="display:inline-flex;align-items:center;gap:6px;color:${inkMuted}"><span style="width:8px;height:8px;border-radius:2px;background:${color}"></span>${label}</span>`
    + `<b style="font-variant-numeric:tabular-nums">${value}</b></div>`;
}
export function tipHead(text: string, inkMuted: string) {
  return `<div style="color:${inkMuted};font-size:11px;margin-bottom:4px">${text}</div>`;
}

/** Percentage points, signed. */
export function pts(v: number | null | undefined, lang: Lang, digits = 1) {
  if (v == null || Number.isNaN(v)) return "–";
  const s = new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits, signDisplay: "exceptZero" }).format(v * 100);
  return `${s} pt${Math.abs(v * 100) >= 2 ? "s" : ""}`;
}

/** Plain-language names for model features. Falls back to the raw column name. */
const FEATURES: Record<string, string> = {
  sig_ma28: "28-day demand average",
  sig_ma91: "91-day demand average",
  sig_ma7: "7-day demand average",
  sig_ewm: "Smoothed recent demand",
  dow_ma4: "Same weekday, last 4 weeks",
  last_signal: "Latest demand signal",
  lag7: "Demand 7 days earlier",
  weekday: "Weekday",
  day_of_year: "Day of year",
  promo_pct: "Promotion depth",
  in_flyer: "In the weekly ad",
  discount_coverage: "Markdown coverage",
  discount_on_target: "Markdown on the target day",
  sibling_promo_share: "Similar products on promo",
  subfamily: "Subfamily",
  family: "Family",
  store_id: "Store",
  fam_store_ma28: "Family × store 28-day average",
  zero_share28: "Zero-sales days (28 d)",
  markdown_share28: "Markdown days (28 d)",
  censored_share28: "Stock-out days (28 d)",
  shelf_life_days: "Shelf life",
  temp_max: "Max temperature",
  temp_anomaly: "Temperature vs normal",
  hot_degree: "Heat degrees",
  precipitation: "Rainfall",
  is_pre_holiday: "Day before a holiday",
  is_holiday: "Public holiday",
  days_to_next_holiday: "Days to next holiday",
  footfall_ma7: "Store traffic (7 d)",
  footfall_trend: "Store traffic trend",
  horizon: "Lead time",
  prediction: "Model prediction",
  units_sold: "Units sold (target)",
};
export function featureLabel(name: string) {
  return FEATURES[name] ?? name;
}

const FORMAT_LABEL: Record<string, string> = {
  supercenter: "Supercenter", supermarket: "Supermarket", neighborhood: "Neighborhood market",
};
export function formatLabel(f: string) {
  return FORMAT_LABEL[f] ?? f;
}
