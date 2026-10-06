"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption, ECharts } from "echarts";
import { useTheme } from "@/lib/theme";

export type Tokens = Record<string, string>;
const TOKEN_NAMES = ["surface", "surface-2", "ink", "ink-2", "ink-3", "grid", "axis", "border", "brand", "muted-series",
  "series-1", "series-2", "series-3", "series-4", "series-5", "series-6", "series-7", "series-8",
  "seq-100", "seq-200", "seq-300", "seq-400", "seq-500", "seq-600", "seq-700", "div-neg", "div-mid", "div-pos",
  "good", "warning", "serious", "critical"];

function useTokens(): Tokens {
  const { resolvedTheme } = useTheme();
  const [tokens, setTokens] = useState<Tokens>({});
  useEffect(() => {
    const read = () => {
      const cs = getComputedStyle(document.documentElement);
      const t: Tokens = {};
      TOKEN_NAMES.forEach((n) => { t[n] = cs.getPropertyValue(`--${n}`).trim(); });
      t.font = getComputedStyle(document.body).fontFamily || "system-ui, sans-serif";   // canvas text metrics need a real family
      setTokens(t);
    };
    read();
    const id = requestAnimationFrame(read);
    return () => cancelAnimationFrame(id);
  }, [resolvedTheme]);
  return tokens;
}

/** Recessive chrome shared by every chart: hairline grid, muted axes, surface-colored tooltip. */
export function baseOption(t: Tokens): EChartsOption {
  return {
    animationDuration: 300,
    textStyle: { fontFamily: t.font, color: t["ink-2"], fontSize: 12 },
    grid: { left: 8, right: 16, top: 28, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: t.surface, borderColor: t.border, borderWidth: 1, padding: [8, 10],
      textStyle: { color: t.ink, fontSize: 12 }, extraCssText: "border-radius:8px;box-shadow:0 6px 20px rgba(0,0,0,0.12);",
    },
    legend: { textStyle: { color: t["ink-2"], fontSize: 12, fontFamily: t.font }, icon: "roundRect", itemWidth: 12, itemHeight: 3, top: 0, left: 0, itemGap: 18 },
  };
}

export function axisStyle(t: Tokens) {
  return {
    axisLine: { lineStyle: { color: t.axis } }, axisTick: { show: false },
    axisLabel: { color: t["ink-3"], fontSize: 11.5 }, splitLine: { lineStyle: { color: t.grid, type: "solid" as const, width: 1 } },
  };
}

export function EChart({ option, height = 260, className, ariaLabel, onClick }: {
  option: (t: Tokens) => EChartsOption; height?: number; className?: string; ariaLabel?: string; onClick?: (p: unknown) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chart = useRef<ECharts | null>(null);
  const tokens = useTokens();
  const opt = useMemo(() => (tokens.ink ? option(tokens) : null), [option, tokens]);
  const latest = useRef<EChartsOption | null>(null);
  const clickRef = useRef(onClick);
  useEffect(() => { clickRef.current = onClick; }, [onClick]);

  useEffect(() => {
    let disposed = false;
    let ro: ResizeObserver | null = null;
    import("echarts").then((echarts) => {
      if (disposed || !ref.current) return;
      chart.current = echarts.init(ref.current, undefined, { renderer: "svg" });
      ro = new ResizeObserver(() => chart.current?.resize());
      ro.observe(ref.current);
      if (latest.current) chart.current.setOption(latest.current, true);
      chart.current.on("click", (p) => clickRef.current?.(p));
    });
    return () => { disposed = true; ro?.disconnect(); chart.current?.dispose(); chart.current = null; };
  }, []);

  // echarts loads asynchronously: keep the latest option for the init above, and apply it if the chart exists
  useEffect(() => {
    latest.current = opt;
    if (chart.current && opt) chart.current.setOption(opt, true);
  }, [opt]);

  return <div ref={ref} role="img" aria-label={ariaLabel} className={className} style={{ height, width: "100%" }} />;
}
