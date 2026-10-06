"use client";

import { useCallback, type ReactNode } from "react";
import type { EChartsOption } from "echarts";
import { ArrowDown, ArrowRight, ArrowUp, BookCheck, ClipboardCheck, RefreshCw, ShoppingBasket } from "lucide-react";
import type { Tokens } from "@/components/charts/echart";
import { useI18n } from "@/lib/i18n";
import { dateLabel, num, pct } from "@/lib/format";
import { Chart, axisFont, chartBase, tipHead, tipRow } from "@/components/domain/validation-shared";

/* eslint-disable @typescript-eslint/no-explicit-any */

/** Colour follows the log source: the daily scoring run keeps slot 1. */
const SOURCE_TOKEN: Record<string, string> = { daily_run: "series-1" };
const SPARE = ["series-6", "series-7"];
export function sourceLabel(s: string) {
  return s === "daily_run" ? "Daily run" : s;
}

/** Weekly WAPE of the logged forecasts against what actually sold (uncensored days). */
export function AccuracyChart({ weekly, reference }: { weekly: any[]; reference?: number | null }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const base = chartBase(t);
    const sources = [...new Set(weekly.map((w) => String(w.source)))].sort((a, b) => (a === "daily_run" ? -1 : b === "daily_run" ? 1 : a.localeCompare(b)));
    const weeks = [...new Set(weekly.map((w) => String(w.week).slice(0, 10)))].sort();
    let spare = 0;
    const token = Object.fromEntries(sources.map((s) => [s, SOURCE_TOKEN[s] ?? SPARE[spare++ % SPARE.length]]));
    const idx = new Map(weekly.map((w) => [`${w.source}|${String(w.week).slice(0, 10)}`, w]));
    const multi = sources.length > 1;
    return {
      ...base,
      grid: { left: 4, right: reference != null ? 96 : 28, top: multi ? 36 : 16, bottom: 4, containLabel: true },
      legend: multi ? { ...(base.legend as object), data: sources.map((s) => sourceLabel(s)), itemGap: 18 } : { show: false },
      tooltip: {
        ...(base.tooltip as object), trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.axis } },
        formatter: (ps: any) => {
          const w = ps[0].axisValue;
          let html = tipHead(`Week of ${dateLabel(w, lang, { day: "numeric", month: "short", year: "numeric" })}`, t["ink-3"]);
          ps.forEach((p: any) => {
            const r = idx.get(`${sources[p.seriesIndex]}|${w}`);
            if (!r) return;
            html += tipRow(p.color, multi ? p.seriesName : "WAPE", pct(r.wape, lang, 1), t["ink-2"]);
            html += `<div style="color:${t["ink-3"]};font-size:11px;margin:0 0 3px 14px">bias ${pct(r.bias, lang, 1, true)} · ${num(r.rows, lang)} rows · ${num(r.markdowns, lang)} markdowns</div>`;
          });
          return html;
        },
      },
      xAxis: { type: "category", data: weeks, boundaryGap: false, ...axisFont(t), splitLine: { show: false },
        axisLabel: { ...axisFont(t).axisLabel, formatter: (v: string) => dateLabel(v, lang), interval: Math.max(0, Math.ceil(weeks.length / 6) - 1) } },
      yAxis: { type: "value", min: 0, splitNumber: 4, ...axisFont(t), axisLabel: { ...axisFont(t).axisLabel, formatter: (v: number) => pct(v, lang) } },
      series: sources.map((s, i) => ({
        name: sourceLabel(s), type: "line", data: weeks.map((w) => idx.get(`${s}|${w}`)?.wape ?? null), connectNulls: false,
        symbol: "circle", symbolSize: 8, showSymbol: weeks.length <= 16,
        lineStyle: { width: 2, color: t[token[s]] }, itemStyle: { color: t[token[s]], borderColor: t.surface, borderWidth: 2 },
        markLine: i === 0 && reference != null ? {
          silent: true, symbol: "none", lineStyle: { color: t["ink-3"], type: "solid", width: 1 },
          label: { position: "end", distance: 8, color: t["ink-3"], fontSize: 11, formatter: `Backtest ${pct(reference, lang, 1)}` },
          data: [{ yAxis: reference }],
        } : undefined,
      })) as any,
    };
  }, [weekly, reference, lang]);
  return <Chart option={option} height={320} ariaLabel="Live forecast error by week" />;
}

/** The closed loop: recommendation → decision → outcome → retraining → recommendation. */
export function FeedbackLoop({ stats }: { stats: [ReactNode, ReactNode, ReactNode, ReactNode] }) {
  const steps = [
    { icon: BookCheck, title: "Recommendation",
      caption: "Every morning: markdown, order and donation per store-product, logged with model versions and exploration propensities." },
    { icon: ClipboardCheck, title: "Store decision",
      caption: "The team accepts, overrides or rejects; every decision is recorded with who made it." },
    { icon: ShoppingBasket, title: "Outcome (sales, waste)",
      caption: "Sales, stock-outs and waste flow back from store systems the next day and are scored against the forecast." },
    { icon: RefreshCw, title: "Retraining (weekly)",
      caption: "The model is retrained weekly; the champion is replaced only if the challenger does better, after a drift check." },
  ];
  return (
    <div>
      <ol className="grid grid-cols-1 gap-3 md:grid-cols-4 md:gap-10">
        {steps.map(({ icon: Icon, title, caption }, i) => (
          <li key={title} className="relative">
            <div className="h-full rounded-xl border border-border bg-surface-2/60 p-4">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand"><Icon className="h-4 w-4" /></span>
                <span className="text-[13.5px] font-semibold text-ink">{title}</span>
              </div>
              <p className="mt-2 text-[12.5px] leading-relaxed text-ink-3">{caption}</p>
              <div className="mt-2.5 text-[12.5px] font-medium text-ink-2 tabular">{stats[i]}</div>
            </div>
            {i < steps.length - 1 && (
              <>
                <ArrowRight aria-hidden className="absolute -right-[30px] top-1/2 hidden h-5 w-5 -translate-y-1/2 text-ink-3 md:block" />
                <ArrowDown aria-hidden className="mx-auto mt-3 h-5 w-5 text-ink-3 md:hidden" />
              </>
            )}
          </li>
        ))}
      </ol>
      {/* return path from retraining back to the next morning's recommendations */}
      <div aria-hidden className="relative mx-[calc(12.5%-15px)] mt-0 hidden h-9 rounded-b-2xl border-x-[1.5px] border-b-[1.5px] border-[var(--axis)] md:block">
        <ArrowUp className="absolute -left-[10.5px] -top-[9px] h-5 w-5 bg-surface text-ink-3" />
        <span className="absolute -bottom-2.5 left-1/2 -translate-x-1/2 whitespace-nowrap bg-surface px-2 text-[12px] text-ink-3">
          The retrained model produces the next morning’s recommendations
        </span>
      </div>
      <p className="mt-3 text-center text-[12px] text-ink-3 md:hidden">↺ back to the next morning’s recommendation</p>
    </div>
  );
}
