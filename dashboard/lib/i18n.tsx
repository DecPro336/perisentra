"use client";

import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { money, type Lang } from "./format";
import type { ReasonCode } from "./api";

type Dict = Record<string, string>;

const en: Dict = {
  "nav.overview": "Overview", "nav.recommendations": "Morning actions", "nav.risk": "Stock at risk",
  "nav.elasticity": "Price response", "nav.validation": "Validation", "nav.models": "Models",
  "nav.monitoring": "Monitoring", "nav.data": "Data & pipeline", "nav.rules": "Business rules",
  "nav.section.operate": "Operate", "nav.section.understand": "Understand", "nav.section.govern": "Govern",
  "top.asof": "Decisions for", "top.allStores": "All stores",
  "top.run": "Run", "top.store": "Store",
  "common.loading": "Loading…", "common.error": "Could not load data", "common.none": "Nothing to show",
  "common.units": "units", "common.search": "Search products…", "common.all": "All", "common.export": "Export CSV",
  "common.view": "View", "common.table": "Table", "common.chart": "Chart", "common.close": "Close",
  "action.MARKDOWN": "Markdown", "action.NO_ACTION": "No action", "order.REDUCE": "Reduce order",
  "order.INCREASE": "Increase order", "order.KEEP": "Keep order", "action.DONATE": "Donate at close",
  "tier.HIGH": "High confidence", "tier.MEDIUM": "Medium confidence", "tier.LOW": "Low confidence",
  "tier.short.HIGH": "High", "tier.short.MEDIUM": "Medium", "tier.short.LOW": "Low",
  "ov.title": "Good morning — here is what to do today",
  "ov.subtitle": "Every recommendation is scored against the forecast, the stock on the shelf and your business rules.",
  "ov.atRisk": "Stock at risk of waste", "ov.atRiskHint": "Expected waste value if nothing is done",
  "ov.avoided": "Waste avoided by today's actions", "ov.markdowns": "Targeted markdowns",
  "ov.vsLegacy": "vs {n} under the current flat rule", "ov.orders": "Order adjustments", "ov.stockouts": "Stock-out alerts",
  "ov.donations": "Donations at close", "ov.marginDelta": "Expected margin vs no action",
  "ov.byStore": "Stores", "ov.byFamily": "By family", "ov.topRisk": "Highest waste risk this morning",
  "ov.trend": "Chain trend (weekly)", "ov.wasteTrend": "Waste value per week", "ov.mdTrend": "Markdown events per week",
  "ov.marginTrend": "Gross margin rate", "ov.stockoutTrend": "Stock-out rate",
  "ov.confidence": "Confidence mix",
  "rec.title": "Morning actions", "rec.subtitle": "One line per product. Open a line to see why, test alternatives and record the store's decision.",
  "rec.filters.action": "Action", "rec.filters.family": "Family", "rec.filters.tier": "Confidence", "rec.filters.onlyActions": "Only lines with an action",
  "rec.col.product": "Product", "rec.col.action": "Recommendation", "rec.col.stock": "On hand", "rec.col.expiring": "Expiring ≤3d",
  "rec.col.forecast": "Forecast today", "rec.col.risk": "Waste risk", "rec.col.avoided": "Avoided", "rec.col.order": "Next order",
  "rec.col.confidence": "Confidence", "rec.col.why": "Why",
  "rec.filter.STOCKOUT": "Stock-out risk", "rec.filter.ORDER": "Order change", "rec.filter.DONATE": "Donation",
  "item.back": "Back to actions", "item.why": "Why this recommendation", "item.forecast": "Demand forecast (next 7 days)",
  "item.history": "Last 9 weeks: sales and censored demand", "item.lots": "Stock on the shelf by expiry",
  "item.candidates": "Every action the engine evaluated", "item.unsold": "Units likely wasted",
  "item.whatif": "What-if simulator", "item.decision": "Store decision", "item.accept": "Apply recommendation",
  "item.override": "Override", "item.reject": "Reject", "item.note": "Note (optional)", "item.logged": "Decision recorded",
  "item.confidenceWhy": "What drives confidence", "item.elasticity": "Price response",
  "item.noAction": "No action", "item.chosen": "Chosen", "item.blocked": "Blocked",
  "item.simulate": "Simulate", "item.discount": "Discount", "item.window": "Labels on units expiring within",
  "item.days": "days", "item.baseline": "No action", "item.scenario": "Your scenario",
  "risk.title": "Stock at risk", "risk.subtitle": "Expected waste value if nothing is done, by store and family.",
  "el.title": "Price response", "el.subtitle": "Learned from the randomized price test, not from historical markdowns.",
  "val.title": "Validation", "val.backtest": "Rolling-origin backtest", "val.pilot": "Pilot vs matched controls",
  "mod.title": "Models", "mon.title": "Monitoring", "data.title": "Data & pipeline", "rules.title": "Business rules",
};


const DRIVERS: Record<string, string> = { holiday: "public holiday", pre_holiday: "day before a holiday", rain: "rain", heat: "warmer than normal", cold: "colder than normal",
        weekday_peak: "strong weekday", weekday_low: "quiet weekday", promotion: "promotion", sibling_promo: "similar products on promotion",
        footfall_down: "store traffic down", out_of_season: "the product leaves the assortment for the season",
};

type Tpl = (p: Record<string, any>) => string; // eslint-disable-line @typescript-eslint/no-explicit-any
const drivers = (p: Record<string, unknown>) =>
  Array.isArray(p.drivers) && p.drivers.length ? ` (${(p.drivers as string[]).map((d) => DRIVERS[d] ?? d).join(", ")})` : "";

const usd = (v: unknown) => money(Number(v), "en", 2);
const within = (days: number) => (days === 1 ? "tonight" : `within ${days} days`);

const REASONS: Record<string, Tpl> = {
    EXPIRY_RISK: (p) => `${p.units} unit${p.units === 1 ? " expires" : "s expire"} ${within(Number(p.days))}: ${p.p_waste}% chance of waste at full price (≈ ${usd(p.waste_amount)}).`,
    MARKDOWN_LIFT: (p) => `A ${p.discount}% sticker lifts demand for those units by about ${p.lift_pct}% (elasticity ${p.elasticity}).`,
    WASTE_AVOIDED: (p) => `Expected waste falls by ${usd(p.amount)} (${p.units} units) versus doing nothing.`,
    PRICE_POINT: (p) => `Price snapped to the ${usd(p.price)} price point.`,
    WILL_SELL_THROUGH: (p) => `${p.units} unit${p.units === 1 ? "" : "s"} close to expiry, but ${p.p_sell}% likely to sell at full price — no markdown needed.`,
    MARKDOWN_NOT_WORTH_IT: () => "A markdown would not reduce waste enough to justify the margin it costs.",
    MARKDOWN_TOO_EARLY: (p) => `Too early for a markdown (allowed from ${p.days} days before expiry): the engine re-checks every morning and adjusts the order meanwhile.`,
    NOT_PROFITABLE: () => "A markdown would not raise expected revenue: the stock is already paid for, so the discount would mostly go to units that sell anyway.",
    PROMO_LOCK: () => "Active promotion: markdowns are locked by the business rules.",
    UNIT_MARGIN_FLOOR: (p) => `Discounts from ${p.from_discount}% would break the unit margin floor.`,
    WINDOW_MARGIN_FLOOR: (p) => `Discounts from ${p.from_discount}% would push the margin over the markdown window below the floor.`,
    MAX_DISCOUNT: () => "Deeper discounts exceed the family's maximum discount.",
    DEMAND_ABOVE_NORMAL: (p) => `Demand expected ${p.pct}% above the 4-week norm${drivers(p)}.`,
    DEMAND_BELOW_NORMAL: (p) => `Demand expected ${Math.abs(p.pct)}% below the 4-week norm${drivers(p)}.`,
    STOCKOUT_RISK: (p) => `${p.p}% chance of running out before the next delivery.`,
    ORDER_REDUCE: (p) => `Reduce the next order from ~${p.reference} to ${p.recommended} units.`,
    ORDER_INCREASE: (p) => `Increase the next order from ~${p.reference} to ${p.recommended} units.`,
    DONATE_AT_CLOSE: (p) => `About ${p.units} units will still be unsold at close: schedule a food-bank donation (the enhanced food-inventory deduction recovers about ${p.benefit_pct ?? 50}% of their cost).`,
    EXPIRY_IMPUTED: () => "Expiry date estimated from delivery date + shelf life (not tracked for this product).",
    THIN_HISTORY: (p) => (p.days > 0
      ? `Only ${p.days} day${p.days > 1 ? "s" : ""} of sales history: the forecast borrows from the family and the store.`
      : "New product with no sales history yet: the forecast borrows from the family and the store."),
    ELASTICITY_BORROWED: (p) => `Not in the price test: price response borrowed from the ${p.family} family.`,
    EXPLORATION: () => "Exploration: chosen at random among equivalent actions to keep learning price response.",
};

interface Ctx { lang: Lang; t: (k: string, vars?: Record<string, string | number>) => string; reason: (r: ReasonCode) => string; driver: (d: string) => string }
const I18nContext = createContext<Ctx | null>(null);

/** UI copy, reason-code templates and demand-driver labels (English). */
export function I18nProvider({ children }: { children: ReactNode }) {
  const t = useCallback((k: string, vars?: Record<string, string | number>) => {
    let s = en[k] ?? k;
    if (vars) Object.entries(vars).forEach(([key, v]) => { s = s.replace(`{${key}}`, String(v)); });
    return s;
  }, []);
  const reason = useCallback((r: ReasonCode) => { const f = REASONS[r.code]; return f ? f(r.params) : r.code; }, []);
  const driver = useCallback((d: string) => DRIVERS[d] ?? d, []);
  const value = useMemo(() => ({ lang: "en" as Lang, t, reason, driver }), [t, reason, driver]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const c = useContext(I18nContext);
  if (!c) throw new Error("I18nProvider missing");
  return c;
}
