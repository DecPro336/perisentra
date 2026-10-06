"use client";

import { useCallback } from "react";
import type { EChartsOption } from "echarts";
import { EChart, axisStyle, baseOption, type Tokens } from "@/components/charts/echart";
import { useI18n } from "@/lib/i18n";
import { num } from "@/lib/format";
import { chartText } from "./risk-charts";

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface FamilyElasticity {
  family: string; mean: number; sd: number; hdi_low: number; hdi_high: number; test_rows: number; test_skus: number;
  naive_elasticity: number | null; naive_rows: number | null; markdown_share: number | null;
}
export interface SkuElasticity {
  sku_id: number; family: string; mean: number; sd: number; hdi_low: number; hdi_high: number;
  source: "posterior" | "family_predictive"; product_name: string | null;
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

/** Dot-and-interval plot per family: posterior mean + 94% HDI (slot 1), naive history estimate (slot 2). */
export function FamilyIntervalChart({ rows }: { rows: FamilyElasticity[] }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const data = [...rows].sort((a, b) => a.mean - b.mean);
    const names = {
      post: "Bayesian (mean, 94% HDI)",
      naive: "Naive (history)",
    };
    const all = data.flatMap((r) => [r.hdi_high, r.naive_elasticity ?? 0]);
    const xMax = Math.ceil((Math.max(...all, 1) + 0.05) * 2) / 2;
    const c1 = t["series-1"];
    const series: any[] = [
      {
        name: names.post, type: "custom", z: 3,
        itemStyle: { color: c1 },
        encode: { x: [0, 2, 3], y: 1 },
        data: data.map((r, i) => [r.mean, i, r.hdi_low, r.hdi_high]),
        renderItem: (_p: any, api: any) => {
          const y = api.value(1);
          const lo = api.coord([api.value(2), y]);
          const hi = api.coord([api.value(3), y]);
          const m = api.coord([api.value(0), y]);
          return {
            type: "group",
            children: [
              { type: "line", shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] }, style: { stroke: c1, lineWidth: 2, lineCap: "round" } },
              { type: "line", shape: { x1: lo[0], y1: lo[1] - 5, x2: lo[0], y2: lo[1] + 5 }, style: { stroke: c1, lineWidth: 2, lineCap: "round" } },
              { type: "line", shape: { x1: hi[0], y1: hi[1] - 5, x2: hi[0], y2: hi[1] + 5 }, style: { stroke: c1, lineWidth: 2, lineCap: "round" } },
              { type: "circle", shape: { cx: m[0], cy: m[1], r: 5.5 }, style: { fill: c1, stroke: t.surface, lineWidth: 2 } },
            ],
          };
        },
      },
      {
        name: names.naive, type: "scatter", z: 4, symbol: "diamond", symbolSize: 12,
        data: data.map((r, i) => [r.naive_elasticity, i]),
        itemStyle: { color: t["series-2"], borderColor: t.surface, borderWidth: 2 },
      },
    ];
    const f2 = (v: number | null | undefined) => (v == null ? "–" : num(v, lang, 2));
    return {
      ...baseOption(t),
      textStyle: chartText(t),
      grid: { left: 4, right: 20, top: 44, bottom: 30, containLabel: true },
      legend: {
        ...(baseOption(t).legend as object), itemWidth: 11, itemHeight: 11, itemGap: 18,
        data: [{ name: names.post, icon: "circle" }, { name: names.naive, icon: "diamond" }],
      },
      tooltip: {
        ...(baseOption(t).tooltip as object), trigger: "axis",
        axisPointer: { type: "shadow", axis: "y", shadowStyle: { color: t["surface-2"], opacity: 0.8 } },
        formatter: (ps: any) => {
          const p = Array.isArray(ps) ? ps[0] : ps;
          const r = data[p?.dataIndex ?? -1];
          if (!r) return "";
          const dot = (c: string, shape: string) => `<span style="display:inline-block;width:8px;height:8px;margin-right:6px;background:${c};${shape}"></span>`;
          const line = (mk: string, label: string, v: string) => `<div style="display:flex;justify-content:space-between;gap:18px"><span>${mk}${label}</span><b>${v}</b></div>`;
          return `<div style="font-weight:600;font-size:13px;margin-bottom:4px">${esc(r.family)}</div>`
            + line(dot(c1, "border-radius:50%"), "Bayesian", `${f2(r.mean)} <span style="font-weight:400;color:${t["ink-3"]}">[${f2(r.hdi_low)}–${f2(r.hdi_high)}]</span>`)
            + line(dot(t["series-2"], "transform:rotate(45deg) scale(.8)"), "Naive (history)", f2(r.naive_elasticity))
            + `<div style="color:${t["ink-3"]};font-size:11px;margin-top:4px">${num(r.test_rows, lang)} test rows · ${r.test_skus} SKUs</div>`;
        },
      },
      xAxis: {
        type: "value", min: 0, max: xMax, ...axisStyle(t),
        name: "Price elasticity (demand response to a price cut)",
        nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t["ink-3"], fontSize: 11 },
      },
      yAxis: { type: "category", data: data.map((r) => r.family), ...axisStyle(t), splitLine: { show: true, lineStyle: { color: t.grid } }, axisLine: { show: false } },
      series,
    };
  }, [rows, lang]);
  return <EChart option={option} height={Math.max(360, rows.length * 40 + 100)} ariaLabel={"Elasticity by family"} />;
}

/** Tested SKUs: posterior mean (x) against the width of the 94% interval (y). Narrow intervals are precise enough
 *  to act on; wide ones mean the price test saw too few discounted days for that product. */
export function SkuPrecisionScatter({ rows }: { rows: SkuElasticity[] }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const f2 = (v: number | null | undefined) => (v == null ? "–" : num(v, lang, 2));
    return {
      ...baseOption(t),
      textStyle: chartText(t),
      grid: { left: 30, right: 24, top: 16, bottom: 34, containLabel: true },
      tooltip: {
        ...(baseOption(t).tooltip as object), trigger: "item",
        formatter: (p: any) => {
          const r = rows[p.dataIndex];
          if (!r) return "";
          return `<div style="font-weight:600;font-size:13px">${esc(r.product_name ?? `SKU ${r.sku_id}`)}</div><div style="color:${t["ink-3"]};font-size:11.5px;margin-bottom:4px">${esc(r.family)} · SKU ${r.sku_id}</div>`
            + `<div>Elasticity: <b>${f2(r.mean)}</b> <span style="color:${t["ink-3"]}">[${f2(r.hdi_low)}–${f2(r.hdi_high)}]</span></div>`
            + `<div>94% interval width: <b>${f2(r.hdi_high - r.hdi_low)}</b></div>`;
        },
      },
      xAxis: { type: "value", scale: true, ...axisStyle(t), name: "Elasticity (posterior mean)", nameLocation: "middle", nameGap: 26, nameTextStyle: { color: t["ink-3"], fontSize: 11 } },
      yAxis: { type: "value", min: 0, ...axisStyle(t), name: "Width of the 94% interval", nameLocation: "middle", nameGap: 34, nameTextStyle: { color: t["ink-3"], fontSize: 11 } },
      series: [{
        type: "scatter", symbolSize: 8, data: rows.map((r) => [r.mean, r.hdi_high - r.hdi_low]),
        itemStyle: { color: t["series-1"], opacity: 0.8, borderColor: t.surface, borderWidth: 1 },
        emphasis: { scale: 1.6, itemStyle: { opacity: 1 } },
      }],
    };
  }, [rows, lang]);
  return <EChart option={option} height={400} ariaLabel={"Precision of the elasticity estimate by SKU"} />;
}
