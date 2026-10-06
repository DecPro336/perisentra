"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import { EChart, axisStyle, baseOption, type Tokens } from "@/components/charts/echart";

/* eslint-disable @typescript-eslint/no-explicit-any */

export type RiskMetric = "at_risk" | "stockout_alerts" | "markdowns";

export interface RiskCell {
  store_id: number; store_name: string; family: string;
  at_risk: number; stockout_alerts: number; markdowns: number; items: number;
}

/** Width of an element, kept in sync with a ResizeObserver (used to adapt axis labels to the cell size). */
function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

/**
 * ECharts measures text on a canvas, where `var(--font-inter)` does not resolve, so legend gaps, label wrapping and
 * truncation get computed with a fallback font. Give it the concrete family so measurement matches the rendered text.
 */
export function chartText(t: Tokens) {
  let fam = "";
  if (typeof document !== "undefined") fam = getComputedStyle(document.documentElement).getPropertyValue("--font-inter").trim();
  return { ...(baseOption(t).textStyle as object), fontFamily: `${fam ? `${fam}, ` : ""}system-ui, -apple-system, "Segoe UI", sans-serif` };
}

const STORE_W = 150;   // left band for store names
const ROW_H = 28;
const N_LABELS = 10;    // only the largest cells carry a direct label

export function RiskHeatmap({ cells, storeOrder, familyOrder, metric, format, metricLabels, onCell }: {
  cells: RiskCell[];
  storeOrder: { store_id: number; store_name: string }[];
  familyOrder: string[];
  metric: RiskMetric;
  format: (m: RiskMetric, v: number) => string;
  metricLabels: Record<RiskMetric, string>;
  onCell: (c: RiskCell) => void;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const colW = width ? (width - STORE_W - 12) / Math.max(1, familyOrder.length) : 80;
  const rotate = colW < 74;
  const showLabels = colW >= 44;
  const top = rotate ? 92 : 46;
  const bottom = 58;
  const height = top + storeOrder.length * ROW_H + bottom;

  const { data, max, min, threshold, lookup } = useMemo(() => {
    const yIdx = new Map(storeOrder.map((s, i) => [s.store_id, i]));
    const xIdx = new Map(familyOrder.map((f, i) => [f, i]));
    const lookup = new Map<string, RiskCell>();
    const vals = cells.map((c) => c[metric]).filter((v) => v > 0).sort((a, b) => b - a);
    const max = vals[0] ?? 1;
    const min = metric === "at_risk" ? 0 : 0.5;
    const threshold = vals[Math.min(N_LABELS, vals.length) - 1] ?? Infinity;
    const data = cells.filter((c) => yIdx.has(c.store_id) && xIdx.has(c.family)).map((c) => {
      const x = xIdx.get(c.family)!, y = yIdx.get(c.store_id)!;
      lookup.set(`${x}-${y}`, c);
      return { value: [x, y, c[metric]] as [number, number, number] };
    });
    return { data, max, min, threshold, lookup };
  }, [cells, storeOrder, familyOrder, metric]);

  const option = useCallback((t: Tokens): EChartsOption => {
    const ramp = [t["seq-100"], t["seq-200"], t["seq-300"], t["seq-400"], t["seq-500"], t["seq-600"], t["seq-700"]];
    const labelled = data.map((d) => {
      const v = d.value[2];
      const show = showLabels && v > 0 && v >= threshold;
      const norm = (v - min) / Math.max(1e-9, max - min);
      return { ...d, label: { show, color: norm > 0.5 ? t.surface : t.ink } };
    });
    return {
      ...baseOption(t),
      textStyle: chartText(t),
      grid: { left: STORE_W, right: 8, top, bottom },
      tooltip: {
        ...(baseOption(t).tooltip as object), trigger: "item",
        formatter: (p: any) => {
          const c = lookup.get(`${p.value[0]}-${p.value[1]}`);
          if (!c) return "";
          const row = (m: RiskMetric) => `<div style="display:flex;justify-content:space-between;gap:16px;${m === metric ? "font-weight:600" : `color:${t["ink-2"]}`}"><span>${metricLabels[m]}</span><span>${format(m, c[m])}</span></div>`;
          return `<div style="font-weight:600;font-size:13px">${esc(c.store_name)}</div><div style="color:${t["ink-3"]};font-size:11.5px;margin-bottom:6px">${esc(c.family)} · ${c.items} products</div>`
            + row("at_risk") + row("stockout_alerts") + row("markdowns")
            + `<div style="color:${t["ink-3"]};font-size:11px;margin-top:6px">Click to open the actions</div>`;
        },
      },
      xAxis: {
        type: "category", data: familyOrder, position: "top", ...axisStyle(t),
        axisLine: { show: false }, splitLine: { show: false }, splitArea: { show: false },
        axisLabel: {
          ...axisStyle(t).axisLabel, interval: 0, color: t["ink-2"], lineHeight: 14,
          ...(rotate ? { rotate: 40, width: 110, overflow: "truncate" as const } : { width: Math.max(40, colW - 8), overflow: "break" as const }),
        },
      },
      yAxis: {
        type: "category", data: storeOrder.map((s) => s.store_name), inverse: true, ...axisStyle(t),
        axisLine: { show: false }, splitLine: { show: false },
        axisLabel: { ...axisStyle(t).axisLabel, color: t["ink-2"], width: STORE_W - 14, overflow: "truncate" },
      },
      visualMap: {
        type: "continuous", min, max, calculable: false, orient: "horizontal", left: STORE_W, bottom: 6,
        itemWidth: 10, itemHeight: 220, hoverLink: true, seriesIndex: 0, dimension: 2,
        text: [format(metric, max), metric === "at_risk" ? format(metric, 0) : "1"], textGap: 8,
        textStyle: { color: t["ink-3"], fontSize: 11 },
        inRange: { color: ramp }, outOfRange: { color: [t["surface-2"]] },
      },
      series: [{
        type: "heatmap", data: labelled as any, cursor: "pointer",
        itemStyle: { borderColor: t.surface, borderWidth: 2, borderRadius: 4 },
        label: { fontSize: 11, fontWeight: 500, formatter: (p: any) => format(metric, p.value[2]) },
        emphasis: { itemStyle: { borderColor: t.ink, borderWidth: 1.5 } },
      }],
    };
  }, [data, lookup, max, min, threshold, showLabels, rotate, colW, top, familyOrder, storeOrder, metric, format, metricLabels]);

  const click = useCallback((p: any) => {
    const c = p?.value ? lookup.get(`${p.value[0]}-${p.value[1]}`) : undefined;
    if (c) onCell(c);
  }, [lookup, onCell]);

  return (
    <div ref={ref}>
      <EChart option={option} height={height} onClick={click} ariaLabel={"Store by family heatmap"} />
    </div>
  );
}

/** Ranked horizontal bars (top N), one series in slot 1, value at the tip. */
export function RankedBars({ rows, format, onClick, ariaLabel }: {
  rows: { key: string; name: string; value: number; sub?: string }[];
  format: (v: number) => string;
  onClick?: (key: string) => void;
  ariaLabel: string;
}) {
  const option = useCallback((t: Tokens): EChartsOption => ({
    ...baseOption(t),
    textStyle: chartText(t),
    grid: { left: 150, right: 64, top: 4, bottom: 4 },
    tooltip: {
      ...(baseOption(t).tooltip as object), trigger: "item",
      formatter: (p: any) => {
        const r = rows[p.dataIndex];
        return `<div style="font-weight:600">${esc(r.name)}</div><div>${format(r.value)}</div>${r.sub ? `<div style="color:${t["ink-3"]};font-size:11px">${esc(r.sub)}</div>` : ""}`;
      },
    },
    xAxis: { type: "value", show: false, max: (v: { max: number }) => v.max * 1.02 },
    yAxis: {
      type: "category", data: rows.map((r) => r.name), inverse: true, ...axisStyle(t),
      axisLine: { show: false }, splitLine: { show: false },
      axisLabel: { ...axisStyle(t).axisLabel, color: t["ink-2"], width: 138, overflow: "truncate" },
    },
    series: [{
      type: "bar", data: rows.map((r) => r.value), barMaxWidth: 14, cursor: onClick ? "pointer" : "default",
      itemStyle: { color: t["series-1"], borderRadius: [0, 4, 4, 0] },
      label: { show: true, position: "right", color: t["ink-2"], fontSize: 11.5, formatter: (p: any) => format(p.value) },
      emphasis: { itemStyle: { color: t["series-1"], opacity: 0.85 } },
    }],
  }), [rows, format, onClick]);
  return <EChart option={option} height={rows.length * 34 + 12} ariaLabel={ariaLabel} onClick={onClick ? (p: any) => onClick(rows[p.dataIndex]?.key) : undefined} />;
}
