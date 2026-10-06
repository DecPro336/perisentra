"use client";

import { useCallback, useMemo } from "react";
import type { EChartsOption } from "echarts";
import { EChart, baseOption, type Tokens } from "@/components/charts/echart";
import { chartText } from "./risk-charts";

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface LineageNode { id: string; name: string; layer: string }
export interface LineageEdge { source: string; target: string }

const LAYERS = ["source", "staging", "intermediate", "marts"];
const NODE_W = 196;
const NODE_H = 22;
const SIDE = NODE_W / 2 + 6;
const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

const LAYER_NAMES: Record<string, string> = { source: "Raw sources", staging: "Staging", intermediate: "Intermediate", marts: "Marts" };

/** dbt lineage as a layered graph: fixed x per layer, nodes sorted by name, hover highlights adjacency. */
export function LineageGraph({ nodes, edges, height = 560 }: { nodes: LineageNode[]; edges: LineageEdge[]; height?: number }) {

  const layout = useMemo(() => {
    const layers = [...LAYERS, ...[...new Set(nodes.map((n) => n.layer))].filter((l) => !LAYERS.includes(l)).sort()];
    const byLayer = new Map<string, LineageNode[]>();
    nodes.forEach((n) => byLayer.set(n.layer, [...(byLayer.get(n.layer) ?? []), n]));
    const used = layers.filter((l) => byLayer.has(l));
    const ids = new Set(nodes.map((n) => n.id));
    const links = edges.filter((e) => ids.has(e.source) && ids.has(e.target));
    const up = new Map<string, number>(), down = new Map<string, number>();
    links.forEach((e) => { down.set(e.source, (down.get(e.source) ?? 0) + 1); up.set(e.target, (up.get(e.target) ?? 0) + 1); });
    const placed = used.flatMap((layer, li) => {
      const list = [...(byLayer.get(layer) ?? [])].sort((a, b) => a.name.localeCompare(b.name));
      return list.map((n, i) => ({ ...n, x: li, y: (i + 0.5) / list.length }));
    });
    return { used, placed, links, up, down };
  }, [nodes, edges]);

  const option = useCallback((t: Tokens): EChartsOption => {
    const { placed, links, up, down, used } = layout;
    const layerOf = new Map(placed.map((n) => [n.id, n.x]));
    const hidden = { show: false };
    return {
      ...baseOption(t),
      textStyle: chartText(t),
      animation: false,
      // Hidden value axes give the graph a linear pixel mapping (x = layer, y = rank within layer).
      grid: { left: SIDE, right: SIDE, top: NODE_H / 2 + 4, bottom: NODE_H / 2 + 4 },
      xAxis: { type: "value", min: 0, max: Math.max(1, used.length - 1), axisLine: hidden, axisTick: hidden, axisLabel: hidden, splitLine: hidden },
      yAxis: { type: "value", min: 0, max: 1, inverse: true, axisLine: hidden, axisTick: hidden, axisLabel: hidden, splitLine: hidden },
      tooltip: {
        ...(baseOption(t).tooltip as object), trigger: "item",
        formatter: (p: any) => {
          if (p.dataType === "edge") {
            const s = placed.find((n) => n.id === p.data.source), d = placed.find((n) => n.id === p.data.target);
            return `${esc(s?.name ?? "")} → ${esc(d?.name ?? "")}`;
          }
          const n = placed.find((x) => x.id === p.data.id);
          if (!n) return "";
          return `<div style="font-weight:600">${esc(n.name)}</div><div style="color:${t["ink-3"]};font-size:11.5px">${LAYER_NAMES[n.layer] ?? n.layer}</div>`
            + `<div style="margin-top:4px">${up.get(n.id) ?? 0} upstream · ${down.get(n.id) ?? 0} downstream</div>`;
        },
      },
      series: [{
        type: "graph", coordinateSystem: "cartesian2d", layout: "none",
        roam: false, draggable: false, z: 3,
        symbol: "rect", symbolSize: [NODE_W, NODE_H],
        itemStyle: { color: t["surface-2"], borderWidth: 0 },
        label: { show: true, position: "inside", color: t.ink, fontSize: 10.5, width: NODE_W - 12, overflow: "truncate", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
        lineStyle: { color: t["muted-series"], width: 1, opacity: 0.6, curveness: 0 },
        emphasis: {
          focus: "adjacency",
          itemStyle: { color: t["seq-100"], borderWidth: 0 },
          lineStyle: { color: t["series-1"], width: 1.5, opacity: 1 },
          label: { fontWeight: 600 },
        },
        blur: { itemStyle: { opacity: 0.35 }, lineStyle: { opacity: 0.06 }, label: { opacity: 0.4 } },
        data: placed.map((n) => ({ id: n.id, name: n.name, value: [n.x, n.y] })) as any,
        links: links.map((e) => {
          const same = layerOf.get(e.source) === layerOf.get(e.target);
          // Same-layer dependencies arc out to the side instead of hiding behind the column of nodes.
          return same ? { source: e.source, target: e.target, lineStyle: { curveness: 0.5 } } : { source: e.source, target: e.target };
        }),
      }],
    };
  }, [layout]);

  const { used } = layout;
  const counts = new Map<string, number>();
  nodes.forEach((n) => counts.set(n.layer, (counts.get(n.layer) ?? 0) + 1));
  return (
    <div>
      <div className="relative mb-2 h-5" style={{ marginLeft: SIDE, marginRight: SIDE }}>
        {used.map((l, i) => (
          <div key={l} className="absolute top-0 -translate-x-1/2 whitespace-nowrap text-[11.5px] font-semibold uppercase tracking-wider text-ink-3"
            style={{ left: `${used.length > 1 ? (100 * i) / (used.length - 1) : 50}%` }}>
            {LAYER_NAMES[l] ?? l} <span className="font-normal normal-case tracking-normal">· {counts.get(l) ?? 0}</span>
          </div>
        ))}
      </div>
      <EChart option={option} height={height} ariaLabel={"dbt lineage graph"} />
    </div>
  );
}
