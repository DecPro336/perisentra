"use client";

import { useCallback } from "react";
import type { EChartsOption } from "echarts";
import { EChart, axisStyle, baseOption, type Tokens } from "@/components/charts/echart";
import { useI18n } from "@/lib/i18n";
import { dateLabel, num, pct } from "@/lib/format";

/* eslint-disable @typescript-eslint/no-explicit-any */

export function ForecastChart({ history, forecast }: { history: any[]; forecast: any[] }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const days = [...history.map((h) => h.date), ...forecast.map((f) => f.date)];
    const hIdx = new Map(history.map((h) => [h.date, h]));
    const fIdx = new Map(forecast.map((f) => [f.date, f]));
    const lastHist = history.at(-1)?.date;
    const sales = days.map((d) => { const h = hIdx.get(d); return h && h.is_open ? h.units_sold : null; });
    const censored = days.map((d) => { const h = hIdx.get(d); return h && h.is_censored ? h.units_sold : null; });
    const md = days.map((d) => { const h = hIdx.get(d); return h && h.is_markdown ? h.units_sold : null; });
    const p50 = days.map((d) => (d === lastHist ? hIdx.get(d)?.units_sold ?? null : fIdx.get(d)?.p50 ?? null));
    const lo95 = days.map((d) => fIdx.get(d)?.p025 ?? null);
    const band95 = days.map((d) => { const f = fIdx.get(d); return f ? f.p975 - f.p025 : null; });
    const lo80 = days.map((d) => fIdx.get(d)?.p10 ?? null);
    const band80 = days.map((d) => { const f = fIdx.get(d); return f ? f.p90 - f.p10 : null; });
    const names = { sales: "Sales", fc: "Forecast (median)", b80: "80% interval",
      b95: "95% interval", cens: "Stock-out: demand ≥ sales", md: "Markdown day" };
    return {
      ...baseOption(t),
      grid: { left: 4, right: 16, top: 40, bottom: 4, containLabel: true },
      legend: { ...(baseOption(t).legend as object), data: [names.sales, names.fc, names.b80, names.cens, names.md], itemGap: 18 },
      tooltip: { ...(baseOption(t).tooltip as object), trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.axis } },
        formatter: (ps: any) => {
          const d = ps[0].axisValue; const f = fIdx.get(d); const h = hIdx.get(d);
          let s = `<div style="color:${t["ink-3"]};font-size:11px;margin-bottom:4px">${dateLabel(d, lang, { weekday: "short", day: "numeric", month: "short" })}</div>`;
          if (h) s += `<div><b>${num(h.units_sold, lang)}</b> ${names.sales.toLowerCase()}${h.is_censored ? ` · <span style="color:${t.serious}">stock-out</span>` : ""}${h.is_markdown ? ` · markdown` : ""}${h.is_open ? "" : ` · closed`}</div>`;
          if (f) s += `<div><b>${num(f.p50, lang, 1)}</b> ${names.fc.toLowerCase()}</div><div style="color:${t["ink-3"]}">80%: ${num(f.p10, lang, 1)}–${num(f.p90, lang, 1)} · 95%: ${num(f.p025, lang, 1)}–${num(f.p975, lang, 1)}</div>`;
          return s;
        } },
      xAxis: { type: "category", data: days, boundaryGap: false, ...axisStyle(t), splitLine: { show: false },
        axisLabel: { ...axisStyle(t).axisLabel, formatter: (v: string) => dateLabel(v, lang), interval: 6 } },
      yAxis: { type: "value", ...axisStyle(t), min: 0 },
      series: [
        { name: "lo95", type: "line", data: lo95, stack: "b95", lineStyle: { opacity: 0 }, symbol: "none", silent: true, tooltip: { show: false } },
        { name: names.b95, type: "line", data: band95, stack: "b95", lineStyle: { opacity: 0 }, symbol: "none", areaStyle: { color: t["series-3"], opacity: 0.08 }, silent: true },
        { name: "lo80", type: "line", data: lo80, stack: "b80", lineStyle: { opacity: 0 }, symbol: "none", silent: true },
        { name: names.b80, type: "line", data: band80, stack: "b80", lineStyle: { opacity: 0 }, symbol: "none", itemStyle: { color: t["series-3"] }, areaStyle: { color: t["series-3"], opacity: 0.16 }, silent: true },
        { name: names.sales, type: "line", data: sales, connectNulls: false, symbol: "none", lineStyle: { width: 2, color: t["series-1"] }, itemStyle: { color: t["series-1"] } },
        { name: names.fc, type: "line", data: p50, symbol: "circle", symbolSize: 7, lineStyle: { width: 2, color: t["series-3"] }, itemStyle: { color: t["series-3"], borderColor: t.surface, borderWidth: 2 } },
        { name: names.cens, type: "scatter", data: censored, symbol: "triangle", symbolSize: 10, itemStyle: { color: t.serious, borderColor: t.surface, borderWidth: 2 } },
        { name: names.md, type: "scatter", data: md, symbol: "circle", symbolSize: 8, itemStyle: { color: t["series-7"], borderColor: t.surface, borderWidth: 2 } },
      ],
    };
  }, [history, forecast, lang]);
  return <EChart option={option} height={300} ariaLabel="Sales history and demand forecast" />;
}

export function LotsChart({ lots, asOf, windowDays }: { lots: any[]; asOf: string; windowDays: number }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const byDate = new Map<string, number>();
    lots.forEach((l) => byDate.set(l.expiry_date, (byDate.get(l.expiry_date) ?? 0) + l.qty_on_hand));
    const dates = [...byDate.keys()].sort();
    const dayOffset = (d: string) => Math.round((new Date(d).getTime() - new Date(asOf).getTime()) / 86400000);
    return {
      ...baseOption(t),
      grid: { left: 4, right: 16, top: 16, bottom: 4, containLabel: true },
      tooltip: { ...(baseOption(t).tooltip as object), trigger: "item",
        formatter: (p: any) => `<div style="color:${t["ink-3"]};font-size:11px">Expires ${dateLabel(p.name, lang, { weekday: "short", day: "numeric", month: "short" })}</div><b>${num(p.value, lang)}</b> units` },
      xAxis: { type: "category", data: dates, ...axisStyle(t), splitLine: { show: false },
        axisLabel: { ...axisStyle(t).axisLabel, formatter: (v: string) => { const o = dayOffset(v); return o === 0 ? "Tonight" : `+${o}d`; } } },
      yAxis: { type: "value", ...axisStyle(t), minInterval: 1 },
      series: [{ type: "bar", barMaxWidth: 24, data: dates.map((d) => ({ value: byDate.get(d), itemStyle: { color: dayOffset(d) < windowDays ? t["series-2"] : t["series-1"], borderRadius: [4, 4, 0, 0] } })),
        label: { show: true, position: "top", color: t["ink-2"], fontSize: 11 } }],
    };
  }, [lots, asOf, windowDays, lang]);
  if (!lots.length) return <div className="py-8 text-center text-[13px] text-ink-3">No stock on the shelf</div>;
  return <EChart option={option} height={220} ariaLabel="Stock on hand by expiry date" />;
}

export function WasteDistChart({ baseline, chosen, labels }: { baseline: number[]; chosen?: number[]; labels: [string, string] }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const n = Math.max(baseline.length, chosen?.length ?? 0);
    let last = 0;
    for (let i = 0; i < n; i++) if ((baseline[i] ?? 0) > 0.004 || (chosen?.[i] ?? 0) > 0.004) last = i;
    const cats = Array.from({ length: last + 1 }, (_, i) => (i === n - 1 ? `${i}+` : String(i)));
    const series: any[] = [{ name: labels[0], type: "bar", barMaxWidth: 16, data: baseline.slice(0, last + 1), itemStyle: { color: t["muted-series"], borderRadius: [4, 4, 0, 0] } }];
    if (chosen) series.push({ name: labels[1], type: "bar", barMaxWidth: 16, data: chosen.slice(0, last + 1), itemStyle: { color: t["series-1"], borderRadius: [4, 4, 0, 0] } });
    return {
      ...baseOption(t),
      grid: { left: 4, right: 8, top: 34, bottom: 4, containLabel: true },
      legend: { ...(baseOption(t).legend as object), itemGap: 18 },
      tooltip: { ...(baseOption(t).tooltip as object), trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: t["surface-2"] } }, valueFormatter: (v: any) => pct(v, lang) },
      xAxis: { type: "category", data: cats, name: "units wasted", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t["ink-3"], fontSize: 11 }, ...axisStyle(t), splitLine: { show: false } },
      yAxis: { type: "value", ...axisStyle(t), axisLabel: { ...axisStyle(t).axisLabel, formatter: (v: number) => pct(v, lang) } },
      series,
    };
  }, [baseline, chosen, labels, lang]);
  return <EChart option={option} height={220} ariaLabel="Distribution of wasted units" />;
}
