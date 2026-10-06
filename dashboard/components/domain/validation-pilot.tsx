"use client";

import { useCallback, useMemo } from "react";
import type { EChartsOption } from "echarts";
import { ArrowRight, PackageX, Percent, ShoppingCart, Tag, TrendingDown } from "lucide-react";
import type { Tokens } from "@/components/charts/echart";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { Badge } from "@/components/ui/badge";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useI18n } from "@/lib/i18n";
import { dateLabel, money, moneyCompact, num, pct, type Lang } from "@/lib/format";
import { Chart, axisFont, chartBase, StatusBadge, SwatchLegend, formatLabel, pts, tipHead, tipRow } from "@/components/domain/validation-shared";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Better = "lower" | "higher" | null;
const METRICS: Record<string, { label: string; better: Better; kind: "money" | "count" | "rate" }> = {
  waste_value: { label: "Waste value", better: "lower", kind: "money" },
  waste_units: { label: "Waste units", better: "lower", kind: "count" },
  markdown_events: { label: "Markdown events", better: null, kind: "count" },
  discount_given: { label: "Discount given", better: null, kind: "money" },
  gross_margin: { label: "Gross margin", better: "higher", kind: "money" },
  net_sales: { label: "Net sales", better: "higher", kind: "money" },
  units_sold: { label: "Units sold", better: "higher", kind: "count" },
  stockout_rate: { label: "Stock-out rate", better: "lower", kind: "rate" },
  margin_rate: { label: "Margin rate", better: "higher", kind: "rate" },
};
const metricName = (k: string) => (METRICS[k] ? METRICS[k].label : k);

function absEffect(k: string, v: number, lang: Lang) {
  const kind = METRICS[k]?.kind;
  if (kind === "rate") return `${pts(v, lang)} absolute`;
  const sign = v > 0 ? "+" : "";
  if (kind === "money") return `${sign}${money(v, lang)} per store-week`;
  return `${sign}${num(v, lang, 1)} per store-week`;
}

function verdict(k: string, d: any) {
  const sig = d.ci_low > 0 || d.ci_high < 0;
  const better = METRICS[k]?.better ?? null;
  if (!sig) return <StatusBadge level="neutral">Not significant</StatusBadge>;
  if (!better) return <Badge variant="outline">Significant change</Badge>;
  const improved = better === "lower" ? d.did_pct < 0 : d.did_pct > 0;
  return improved ? <StatusBadge level="good">Improvement</StatusBadge> : <StatusBadge level="critical">Deterioration</StatusBadge>;
}

function SmallMultiple({ weeks, tr, ct, title, format, start, end }: {
  weeks: string[]; tr: (number | null)[]; ct: (number | null)[]; title: string; format: (v: number) => string; start: string; end: string;
}) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const base = chartBase(t);
    const names = ["Pilot stores", "Matched controls"];
    const a = weeks.find((w) => w >= start);
    const b = weeks.filter((w) => w <= end).at(-1);
    return {
      ...base,
      grid: { left: 4, right: 12, top: 14, bottom: 4, containLabel: true },
      legend: { show: false }, // one shared legend for the small multiples sits in the card header
      tooltip: {
        ...(base.tooltip as object), trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.axis } },
        formatter: (ps: any) => {
          const w = ps[0].axisValue;
          const inPilot = w >= start && w <= end;
          return tipHead(`Week of ${dateLabel(w, lang, { day: "numeric", month: "short", year: "numeric" })}${inPilot ? ` · pilot` : ""}`, t["ink-3"])
            + ps.map((p: any) => tipRow(p.color, p.seriesName, p.value == null ? "–" : format(p.value), t["ink-2"])).join("");
        },
      },
      xAxis: { type: "category", data: weeks, boundaryGap: false, ...axisFont(t), splitLine: { show: false },
        axisLabel: { ...axisFont(t).axisLabel, formatter: (v: string) => dateLabel(v, lang), interval: Math.max(0, Math.ceil(weeks.length / 4) - 1) } },
      yAxis: { type: "value", scale: true, splitNumber: 3, ...axisFont(t), axisLabel: { ...axisFont(t).axisLabel, formatter: (v: number) => format(v) } },
      series: [
        { name: names[0], type: "line", data: tr, showSymbol: false, symbolSize: 8, lineStyle: { width: 2, color: t["series-1"] }, itemStyle: { color: t["series-1"], borderColor: t.surface, borderWidth: 2 }, z: 3,
          markArea: a && b ? { silent: true, itemStyle: { color: t["surface-2"], opacity: 1 }, label: { show: false },
            data: [[{ xAxis: a }, { xAxis: b }]] } : undefined },
        { name: names[1], type: "line", data: ct, showSymbol: false, symbolSize: 8, lineStyle: { width: 2, color: t["series-2"] }, itemStyle: { color: t["series-2"], borderColor: t.surface, borderWidth: 2 }, z: 2 },
      ] as any,
    };
  }, [weeks, tr, ct, format, start, end, lang]);
  return (
    <div>
      <div className="mb-1 text-[12.5px] font-medium text-ink-2">{title}</div>
      <Chart option={option} height={170} ariaLabel={title} />
    </div>
  );
}

/** Forest plot: DiD estimate with its 95% CI per metric (the zero line is "no effect"). */
function ForestPlot({ rows }: { rows: { key: string; did: any }[] }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const base = chartBase(t);
    const name = "DiD estimate (95% CI)";
    const cats = rows.map((r) => metricName(r.key));
    const fmt = (v: number) => pct(v / 100, lang, 1, true);
    return {
      ...base,
      grid: { left: 16, right: 20, top: 12, bottom: 4, containLabel: true },
      legend: { show: false },
      tooltip: {
        ...(base.tooltip as object), trigger: "item",
        formatter: (p: any) => {
          const r = rows[Array.isArray(p.value) ? p.value[p.seriesType === "custom" ? 2 : 1] : p.dataIndex];
          if (!r) return "";
          return tipHead(metricName(r.key), t["ink-3"])
            + tipRow(t["series-1"], name, fmt(r.did.did_pct), t["ink-2"])
            + `<div style="color:${t["ink-3"]};font-size:11px;margin:-1px 0 3px 14px">95% CI ${fmt(r.did.ci_low)} to ${fmt(r.did.ci_high)}</div>`;
        },
      },
      xAxis: { type: "value", ...axisFont(t), splitNumber: 5, axisLabel: { ...axisFont(t).axisLabel, formatter: (v: number) => pct(v / 100, lang, 0, true) } },
      yAxis: { type: "category", inverse: true, data: cats, ...axisFont(t), splitLine: { show: false }, axisLine: { show: false },
        axisLabel: { ...axisFont(t).axisLabel, color: t["ink-2"] } },
      series: [
        { name, type: "custom", data: rows.map((r, i) => [r.did.ci_low, r.did.ci_high, i]),
          renderItem: (_params: any, api: any) => {
            const lo = api.coord([api.value(0), api.value(2)]);
            const hi = api.coord([api.value(1), api.value(2)]);
            const style = { stroke: t["series-1"], lineWidth: 2 };
            return { type: "group", children: [
              { type: "line", shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] }, style },
              { type: "line", shape: { x1: lo[0], y1: lo[1] - 5, x2: lo[0], y2: lo[1] + 5 }, style },
              { type: "line", shape: { x1: hi[0], y1: hi[1] - 5, x2: hi[0], y2: hi[1] + 5 }, style },
            ] };
          },
          itemStyle: { color: t["series-1"] }, encode: { x: [0, 1], y: 2 }, z: 1,
          markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: t.axis, type: "dashed", width: 1 },
            data: [{ xAxis: 0 }] } },
        { name, type: "scatter", data: rows.map((r, i) => [r.did.did_pct, i]), symbol: "circle", symbolSize: 11,
          itemStyle: { color: t["series-1"], borderColor: t.surface, borderWidth: 2 }, z: 3 },
      ] as any,
    };
  }, [rows, lang]);
  return <Chart option={option} height={rows.length * 40 + 30} ariaLabel="Pilot effects with 95% confidence intervals" />;
}

export function PilotView({ data }: { data: any }) {
  const { lang } = useI18n();
  const d = data.design ?? {};
  const did = data.did ?? {};
  const storeName = useMemo(() => {
    const m = new Map<number, any>((data.stores ?? []).map((s: any) => [s.store_id, s]));
    return (id: number) => m.get(id)?.store_name ?? `Store ${id}`;
  }, [data.stores]);

  const weekly: any[] = useMemo(() => data.weekly ?? [], [data.weekly]);
  // A week not fully delivered yet would show a fake drop: leave it out.
  const complete = useCallback((w: string) => {
    if (!data.data_end) return true;
    const end = new Date(`${w}T00:00:00Z`);
    end.setUTCDate(end.getUTCDate() + 6);
    return end.toISOString().slice(0, 10) <= String(data.data_end).slice(0, 10);
  }, [data.data_end]);
  const weeks = useMemo(() => [...new Set(weekly.filter((w) => w.group === "treatment" || w.group === "control").map((w) => String(w.week_start)))].filter(complete).sort(), [weekly, complete]);
  const series = useCallback((group: string, field: string) => {
    const m = new Map(weekly.filter((w) => w.group === group).map((w) => [String(w.week_start), w[field]]));
    return weeks.map((w) => (m.has(w) ? (m.get(w) as number) : null));
  }, [weekly, weeks]);

  const fmtMoney = useCallback((v: number) => moneyCompact(v, lang), [lang]);
  const fmtNum = useCallback((v: number) => num(v, lang), [lang]);
  const fmtPct = useCallback((v: number) => pct(v, lang, 1), [lang]);

  const tiles: { key: string; icon: React.ReactNode }[] = [
    { key: "waste_value", icon: <TrendingDown className="h-4 w-4" /> },
    { key: "markdown_events", icon: <Tag className="h-4 w-4" /> },
    { key: "margin_rate", icon: <Percent className="h-4 w-4" /> },
    { key: "stockout_rate", icon: <PackageX className="h-4 w-4" /> },
    { key: "net_sales", icon: <ShoppingCart className="h-4 w-4" /> },
  ];
  const effectRows = Object.keys(METRICS).filter((k) => did[k]).map((k) => ({ key: k, did: did[k] }));
  const significant = effectRows.filter((r) => r.did.ci_low > 0 || r.did.ci_high < 0).length;
  const waste = did.waste_value;
  const period = `${dateLabel(d.start, lang, { day: "numeric", month: "short" })} – ${dateLabel(d.end, lang, { day: "numeric", month: "short", year: "numeric" })}`;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {tiles.filter((x) => did[x.key]).map(({ key, icon }) => {
          const r = did[key];
          return (
            <Stat key={key} icon={icon} label={metricName(key)} value={pct(r.did_pct / 100, lang, 1, true)}
              hint={`Difference-in-differences vs matched controls over the pilot window. Baseline: ${METRICS[key].kind === "rate" ? pct(r.treatment_pre, lang, 1) : METRICS[key].kind === "money" ? money(r.treatment_pre, lang) : num(r.treatment_pre, lang, 1)} per store-week before the pilot.`}
              delta={
                <div className="space-y-1.5">
                  <div className="tabular">95% CI {pct(r.ci_low / 100, lang, 1, true)} to {pct(r.ci_high / 100, lang, 1, true)}</div>
                  <div className="text-[11.5px]">{absEffect(key, r.did_per_store_week, lang)}</div>
                  <div>{verdict(key, r)}</div>
                </div>
              } />
          );
        })}
      </div>

      <Card>
        <CardHeader title={"Weekly averages: pilot vs matched controls"}
          subtitle={`Average per store. Shaded: pilot window (${period}). Lines should run parallel before it; the gap that opens inside is the engine's effect.`}
          actions={<SwatchLegend items={[{ label: "Pilot stores", color: "var(--series-1)" }, { label: "Matched controls", color: "var(--series-2)" },
            { label: "Pilot window", color: "var(--surface-2)", shape: "block" }]} />} />
        <CardBody className="grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2 xl:grid-cols-4">
          <SmallMultiple weeks={weeks} tr={series("treatment", "waste_value")} ct={series("control", "waste_value")} title={metricName("waste_value")} format={fmtMoney} start={d.start} end={d.end} />
          <SmallMultiple weeks={weeks} tr={series("treatment", "markdown_events")} ct={series("control", "markdown_events")} title={metricName("markdown_events")} format={fmtNum} start={d.start} end={d.end} />
          <SmallMultiple weeks={weeks} tr={series("treatment", "margin_rate")} ct={series("control", "margin_rate")} title={metricName("margin_rate")} format={fmtPct} start={d.start} end={d.end} />
          <SmallMultiple weeks={weeks} tr={series("treatment", "stockout_rate")} ct={series("control", "stockout_rate")} title={metricName("stockout_rate")} format={fmtPct} start={d.start} end={d.end} />
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title={"Effect per metric"}
            subtitle={`${significant} of ${effectRows.length} metrics moved significantly (95% CI excluding zero) in the pilot stores against their matched controls.`} />
          <CardBody className="space-y-4">
            {effectRows.length > 0 && <ForestPlot rows={effectRows} />}
            {effectRows.length > 0 && (
              <Table>
                <THead><TR><TH>Metric</TH><TH align="right">DiD estimate</TH><TH align="right">95% CI</TH><TH align="right">Per store-week</TH><TH>Verdict</TH></TR></THead>
                <tbody>
                  {effectRows.map((r) => (
                    <TR key={r.key}>
                      <TD>{metricName(r.key)}</TD>
                      <TD align="right" className="font-medium">{pct(r.did.did_pct / 100, lang, 1, true)}</TD>
                      <TD align="right" className="whitespace-nowrap text-ink-2">{pct(r.did.ci_low / 100, lang, 1, true)} … {pct(r.did.ci_high / 100, lang, 1, true)}</TD>
                      <TD align="right" className="whitespace-nowrap text-ink-2">{absEffect(r.key, r.did.did_per_store_week, lang).replace(" per store-week", "")}</TD>
                      <TD>{verdict(r.key, r.did)}</TD>
                    </TR>
                  ))}
                </tbody>
              </Table>
            )}
          </CardBody>
        </Card>

        <div className="space-y-6 xl:col-span-2">
          <Card>
            <CardHeader title={"Matched pairs"}
              subtitle={"Each pilot store is paired with the closest store of the same format on pre-pilot sales, waste rate, markdown rate and last summer's seasonal profile."} />
            <CardBody className="px-2">
              <Table>
                <THead><TR><TH>Pilot store</TH><TH /><TH>Control</TH><TH>Format</TH><TH align="right">Distance</TH></TR></THead>
                <tbody>
                  {(d.pairs ?? []).map((p: any) => (
                    <TR key={`${p.treatment}-${p.control}`}>
                      <TD className="font-medium">{storeName(p.treatment)}</TD>
                      <TD className="px-0 text-ink-3"><ArrowRight className="h-3.5 w-3.5" /></TD>
                      <TD>{storeName(p.control)}</TD>
                      <TD className="text-ink-2">{formatLabel(p.format)}</TD>
                      <TD align="right">{num(p.distance, lang, 2)}</TD>
                    </TR>
                  ))}
                </tbody>
              </Table>
              <p className="px-3 pt-2 text-[12px] text-ink-3">Distance in standardised units: lower = closer match.</p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader title={"Design notes"} subtitle={"Fixed before the start, from pre-period data only."} />
            <CardBody>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-[13px]">
                <dt className="text-ink-3">Pilot window</dt><dd className="text-ink">{period}</dd>
                <dt className="text-ink-3">Pre-period</dt><dd className="text-ink">{`${d.pre_weeks} weeks before the start`}</dd>
                <dt className="text-ink-3">Stores</dt><dd className="text-ink">{`${(d.treatment ?? []).length} pilot, ${(d.control ?? []).length} matched controls`}</dd>
                <dt className="text-ink-3">Task list</dt><dd className="text-ink">{data.compliance != null ? `${pct(data.compliance, lang)} of items carried out by the pilot stores (store app)` : "Sent to the pilot stores every morning"}</dd>
                <dt className="text-ink-3">After the pilot</dt><dd className="text-ink">Pilot stores keep receiving the daily task list</dd>
                <dt className="text-ink-3">Kept on current rule</dt><dd className="text-ink-2">{(d.rest ?? []).map(storeName).join(", ") || "–"}</dd>
              </dl>
              <p className="mt-3 text-[12px] leading-relaxed text-ink-3">
                Readout: difference-in-differences on weekly store outcomes; each control’s trend is scaled to its pilot store’s level. 95% CIs from a bootstrap over matched pairs (2,000 resamples).
                {waste ? ` Pre-pilot waste: ${money(waste.treatment_pre, lang)} per store-week.` : ""}
              </p>
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
