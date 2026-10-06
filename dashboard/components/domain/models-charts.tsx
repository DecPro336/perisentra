"use client";

import { useCallback } from "react";
import type { EChartsOption } from "echarts";
import { Check, Minus } from "lucide-react";
import type { Tokens } from "@/components/charts/echart";
import { Badge } from "@/components/ui/badge";
import { Tip } from "@/components/ui/tooltip";
import { useI18n } from "@/lib/i18n";
import { num, pct } from "@/lib/format";
import { Chart, axisFont, chartBase, featureLabel, tipHead } from "@/components/domain/validation-shared";

/* eslint-disable @typescript-eslint/no-explicit-any */

/** Top features by share of split gain: one series, value at the bar tip. */
export function ImportanceChart({ rows }: { rows: { feature: string; gain: number; share: number }[] }) {
  const { lang } = useI18n();
  const top = [...rows].sort((a, b) => b.share - a.share).slice(0, 15);
  const option = useCallback((t: Tokens): EChartsOption => {
    const base = chartBase(t);
    return {
      ...base,
      grid: { left: 4, right: 52, top: 8, bottom: 4, containLabel: true },
      tooltip: {
        ...(base.tooltip as object), trigger: "item",
        formatter: (p: any) => {
          const r = top[p.dataIndex];
          return tipHead(`${featureLabel(r.feature)} · <span style="font-family:ui-monospace,monospace">${r.feature}</span>`, t["ink-3"])
            + `<div><b>${pct(r.share, lang, 1)}</b> of total gain</div>`;
        },
      },
      xAxis: { type: "value", ...axisFont(t), splitNumber: 4, axisLabel: { ...axisFont(t).axisLabel, formatter: (v: number) => pct(v, lang) } },
      yAxis: { type: "category", inverse: true, data: top.map((r) => featureLabel(r.feature)), ...axisFont(t), splitLine: { show: false } },
      series: [{
        type: "bar", data: top.map((r) => r.share), barWidth: 12,
        itemStyle: { color: t["series-1"], borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right", distance: 6, color: t["ink-2"], fontSize: 11, formatter: (p: any) => pct(p.value, lang, p.value < 0.01 ? 1 : 0) },
      }],
    };
  }, [top, lang]);
  return <Chart option={option} height={top.length * 26 + 40} ariaLabel="Feature importance" />;
}

/** Weather ablation as diverging rows: WAPE gain from weather features, centred on zero. */
export function WeatherAblation({ rows }: { rows: { family: string; wape_with: number; wape_without: number; gain_pct: number; rows: number; keep_weather: boolean }[] }) {
  const { lang } = useI18n();
  const sorted = [...rows].sort((a, b) => b.gain_pct - a.gain_pct);
  const maxAbs = Math.max(0.5, ...sorted.map((r) => Math.abs(r.gain_pct)));
  return (
    <div>
      <div className="mb-2 grid grid-cols-[92px_minmax(48px,1fr)_50px_82px] items-center gap-2 sm:grid-cols-[minmax(110px,150px)_minmax(0,1fr)_56px_86px] sm:gap-3 text-[11.5px] text-ink-3">
        <span>Family</span>
        <span className="flex justify-between gap-2"><span className="hidden whitespace-nowrap sm:inline">← hurts</span><span className="hidden whitespace-nowrap sm:inline">helps →</span></span>
        <span className="text-right">Gain</span>
        <span>Decision</span>
      </div>
      <ul className="space-y-0.5">
        {sorted.map((r) => {
          const w = (Math.abs(r.gain_pct) / maxAbs) * 50;
          const pos = r.gain_pct >= 0;
          return (
            <Tip key={r.family} side="left" content={
              <div className="space-y-0.5">
                <div className="font-medium text-ink">{r.family}</div>
                <div className="tabular">WAPE with weather {pct(r.wape_with, lang, 1)} · without {pct(r.wape_without, lang, 1)}</div>
                <div className="tabular text-ink-3">{num(r.rows, lang)} validation rows</div>
              </div>
            }>
              <li tabIndex={0} className="grid grid-cols-[92px_minmax(48px,1fr)_50px_82px] items-center gap-2 sm:grid-cols-[minmax(110px,150px)_minmax(0,1fr)_56px_86px] sm:gap-3 rounded-md px-0 py-1 hover:bg-surface-2 focus-visible:bg-surface-2">
                <span className="truncate text-[13px] text-ink" title={r.family}>{r.family}</span>
                <span className="relative h-3">
                  <span className="absolute inset-y-[-3px] left-1/2 w-px bg-[var(--axis)]" />
                  <span className="absolute top-0 h-3"
                    style={pos
                      ? { left: "50%", width: `${w}%`, background: "var(--div-pos)", borderRadius: "0 4px 4px 0" }
                      : { right: "50%", width: `${w}%`, background: "var(--div-neg)", borderRadius: "4px 0 0 4px" }} />
                </span>
                <span className="text-right text-[12.5px] tabular text-ink-2">{pct(r.gain_pct / 100, lang, 1, true)}</span>
                <span>{r.keep_weather
                  ? <Badge variant="neutral" icon={<Check className="h-3 w-3" />}>Kept</Badge>
                  : <Badge variant="outline" icon={<Minus className="h-3 w-3" />}>Dropped</Badge>}</span>
              </li>
            </Tip>
          );
        })}
      </ul>
    </div>
  );
}
