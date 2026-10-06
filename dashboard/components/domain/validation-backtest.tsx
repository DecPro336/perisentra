"use client";

import { useCallback } from "react";
import type { EChartsOption } from "echarts";
import { CalendarRange, Gauge, Scale, Target } from "lucide-react";
import type { Tokens } from "@/components/charts/echart";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { Badge } from "@/components/ui/badge";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useI18n } from "@/lib/i18n";
import { dateLabel, num, pct } from "@/lib/format";
import { Chart, axisFont, chartBase, METHODS, METHOD_TOKEN, StatusBadge, methodLabel, pts, tipHead, tipRow, type Method } from "@/components/domain/validation-shared";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Block = Record<Method, { wape: number; bias: number }>;

function shortLabel(m: Method) {
  return { model: "Perisentra", legacy: "Current rule", seasonal_naive: "Naive D-7", ma28: "28-d avg" }[m];
}

function coverageLevel(cov: number | null | undefined, target: number): "good" | "warning" {
  return cov != null && Math.abs(cov - target) <= 0.05 ? "good" : "warning";
}

function HorizonChart({ rows, height }: { rows: any[]; height: number }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => {
    const base = chartBase(t);
    const lead = (h: number | string) => (`D+${h}`);
    return {
      ...base,
      grid: { left: 4, right: 56, top: 40, bottom: 4, containLabel: true },
      legend: { ...(base.legend as object), data: METHODS.map((m) => methodLabel(m)), itemGap: 18 },
      tooltip: {
        ...(base.tooltip as object), trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.axis } },
        formatter: (ps: any) => {
          const h = ps[0].axisValue;
          const head = tipHead(`Lead time ${lead(h)} · WAPE`, t["ink-3"]);
          return head + ps.map((p: any) => tipRow(p.color, p.seriesName, pct(p.value, lang, 1), t["ink-2"])).join("");
        },
      },
      xAxis: { type: "category", data: rows.map((r) => String(r.horizon)), boundaryGap: false, ...axisFont(t), splitLine: { show: false },
        axisLabel: { ...axisFont(t).axisLabel, formatter: (v: string) => lead(v) } },
      yAxis: { type: "value", scale: true, splitNumber: 4, ...axisFont(t), axisLabel: { ...axisFont(t).axisLabel, formatter: (v: number) => pct(v, lang) } },
      series: METHODS.map((m) => ({
        name: methodLabel(m), type: "line", data: rows.map((r) => r[m]), symbol: "circle", symbolSize: 8,
        lineStyle: { width: 2, color: t[METHOD_TOKEN[m]] }, itemStyle: { color: t[METHOD_TOKEN[m]], borderColor: t.surface, borderWidth: 2 },
        endLabel: m === "model" || m === "seasonal_naive"
          ? { show: true, color: t["ink-2"], fontSize: 11.5, fontWeight: m === "model" ? 600 : 400, distance: 8, formatter: (p: any) => pct(p.value, lang, 1) } : undefined,
        z: m === "model" ? 5 : 2,
      })) as any,
    };
  }, [rows, lang]);
  return <Chart option={option} height={height} ariaLabel="Forecast error by lead time" />;
}

const familyChartHeight = (n: number) => Math.max(300, n * 32 + 44);

function FamilyChart({ rows }: { rows: any[] }) {
  const { lang } = useI18n();
  const sorted = [...rows].sort((a, b) => b.legacy - a.legacy);
  const option = useCallback((t: Tokens): EChartsOption => {
    const base = chartBase(t);
    const names = [methodLabel("model"), methodLabel("legacy")];
    return {
      ...base,
      grid: { left: 4, right: 44, top: 30, bottom: 4, containLabel: true },
      legend: { ...(base.legend as object), data: names, itemGap: 18 },
      tooltip: {
        ...(base.tooltip as object), trigger: "item",
        formatter: (p: any) => {
          const r = sorted[p.dataIndex];
          const gain = r.legacy > 0 ? 1 - r.model / r.legacy : 0;
          return tipHead(`${r.family} · WAPE`, t["ink-3"])
            + tipRow(t["series-1"], names[0], pct(r.model, lang, 1), t["ink-2"])
            + tipRow(t["series-2"], names[1], pct(r.legacy, lang, 1), t["ink-2"])
            + `<div style="margin-top:4px;color:${t["ink-3"]};font-size:11px">Error reduced by ${pct(gain, lang, 0)} · ${num(r.units, lang)} units evaluated</div>`;
        },
      },
      xAxis: { type: "value", ...axisFont(t), axisLabel: { ...axisFont(t).axisLabel, formatter: (v: number) => pct(v, lang) }, splitNumber: 4 },
      yAxis: { type: "category", inverse: true, data: sorted.map((r) => r.family), ...axisFont(t), splitLine: { show: false } },
      series: [
        { name: names[0], type: "bar", data: sorted.map((r) => r.model), barWidth: 9, barGap: "22%",
          itemStyle: { color: t["series-1"], borderRadius: [0, 4, 4, 0] } },
        { name: names[1], type: "bar", data: sorted.map((r) => r.legacy), barWidth: 9,
          itemStyle: { color: t["series-2"], borderRadius: [0, 4, 4, 0] } },
        // Perisentra's value, placed just past the longer of the two bars so it never sits on a bar.
        { name: "label", type: "scatter", silent: true, tooltip: { show: false }, symbolSize: 0,
          data: sorted.map((r) => [Math.max(r.model, r.legacy), r.family, r.model]),
          label: { show: true, position: "right", distance: 6, color: t["ink-2"], fontSize: 11, formatter: (p: any) => pct(p.value[2], lang, 0) } },
      ] as any,
    };
  }, [sorted, lang]);
  return <Chart option={option} height={familyChartHeight(sorted.length)} ariaLabel="Forecast error by product family" />;
}

export function BacktestView({ data }: { data: any }) {
  const { lang } = useI18n();
  const obs: Block = data.observed_uncensored;
  const model = obs.model, legacy = obs.legacy;
  const improvement = legacy.wape > 0 ? 1 - model.wape / legacy.wape : 0;
  const cov80 = data.coverage?.["80"], cov95 = data.coverage?.["95"];
  const horizon: any[] = data.by_horizon ?? [];
  const winsAll = horizon.length > 0 && horizon.every((h) => METHODS.every((m) => m === "model" || h.model <= h[m]));
  const families: any[] = data.by_family ?? [];
  const famWins = families.filter((f) => f.model < f.legacy).length;

  const stockout: (Block & { share_of_rows?: number }) | undefined = data.stockout_days;

  const covFam: any[] = data.coverage_by_family ?? [];
  const famOff = covFam.filter((f) => coverageLevel(f["80"], 0.8) === "warning" || coverageLevel(f["95"], 0.95) === "warning").length;
  const origins: string[] = data.origins ?? [];
  const byOrigin: any[] = data.by_origin ?? [];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat accent icon={<Gauge className="h-4 w-4" />} label={"Forecast error (WAPE)"}
          value={pct(model.wape, lang, 1)}
          hint={"Weighted absolute percentage error: sum of absolute errors / sum of sales, on days without a stock-out."}
          delta={`${pct(improvement, lang, 0)} lower than the current rule (${pct(legacy.wape, lang, 1)})`} />
        <Stat icon={<Scale className="h-4 w-4" />} label={"Forecast bias"}
          value={pct(model.bias, lang, 1, true)}
          hint={"Positive = forecast above sales. Measured on days without a stock-out only, which skew towards quieter days, so every method reads slightly high here. See “Why censoring matters”."}
          delta={`Current rule ${pct(legacy.bias, lang, 1, true)} on the same days`} />
        <Stat icon={<Target className="h-4 w-4" />} label={"80% interval coverage"} value={pct(cov80, lang, 1)}
          hint={"Share of actual sales that fall inside the predicted interval. Target: 80%."}
          delta={<span className="inline-flex flex-wrap items-center gap-2">Target 80% · {pts(cov80 - 0.8, lang)}<StatusBadge level={coverageLevel(cov80, 0.8)}>{coverageLevel(cov80, 0.8) === "good" ? "Calibrated" : "Off target"}</StatusBadge></span>} />
        <Stat icon={<Target className="h-4 w-4" />} label={"95% interval coverage"} value={pct(cov95, lang, 1)}
          hint={"Share of actual sales that fall inside the predicted interval. Target: 95%."}
          delta={<span className="inline-flex flex-wrap items-center gap-2">Target 95% · {pts(cov95 - 0.95, lang)}<StatusBadge level={coverageLevel(cov95, 0.95)}>{coverageLevel(cov95, 0.95) === "good" ? "Calibrated" : "Off target"}</StatusBadge></span>} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title={"Forecast error by lead time"}
            subtitle={winsAll
              ? "Perisentra beats every baseline at every lead time, from 1 to 7 days ahead."
              : "WAPE by lead time, 1 to 7 days ahead. Lower is better."} />
          <CardBody><HorizonChart rows={horizon} height={familyChartHeight(families.length)} /></CardBody>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader title={"Forecast error by family"}
            subtitle={`Perisentra beats the current rule in ${famWins} of ${families.length} families.`} />
          <CardBody><FamilyChart rows={families} /></CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={"Why stock-outs matter"}
          subtitle={stockout
            ? `${pct(stockout.share_of_rows ?? 0, lang, 0)} of evaluated store-SKU-days sold out: on those days sales only show a lower bound on demand.`
            : undefined} />
        <CardBody className="grid grid-cols-1 gap-x-8 gap-y-5 xl:grid-cols-2">
          <div className="space-y-2.5 text-[13px] leading-relaxed text-ink-2">
            <p>When a product sells out, sales stop at the stock level, so they understate demand. The store’s current rule learns from these capped sales, forecasts low, under-orders and causes more stock-outs: a self-reinforcing loop.</p>
            <p>Perisentra treats a stock-out day as a censored observation (demand ≥ sales) and estimates the missing demand with EM. Every method forecasts below what sold on stock-out days (a stock-out happens when demand runs high), but the closer to those sales, the less demand is left unplanned.</p>
          </div>
          {stockout && (
            <Table>
              <THead><TR><TH>Method</TH><TH align="right">Forecast vs units sold on stock-out days (closer to 0 is better)</TH></TR></THead>
              <tbody>
                {(["model", "legacy", "seasonal_naive", "ma28"] as Method[]).map((m) => (
                  <TR key={m}>
                    <TD><span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: `var(--${METHOD_TOKEN[m]})` }} /><span className={m === "model" ? "font-medium" : ""}>{methodLabel(m)}</span></span></TD>
                    <TD align="right" className={m === "model" ? "font-medium" : "text-ink-2"}>{pct(stockout[m].bias, lang, 1, true)}</TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card className="self-start">
          <CardHeader title={"Interval coverage by family"}
            subtitle={famOff === 0
              ? "Every family is within ±5 points of target: the intervals can be trusted."
              : (`${famOff} family(ies) more than 5 points off target.`)} />
          <CardBody className="px-2">
            <Table>
              <THead><TR><TH>Family</TH><TH align="right">80% (target)</TH><TH align="right">95% (target)</TH><TH>Status</TH></TR></THead>
              <tbody>
                <TR className="bg-surface-2/60">
                  <TD className="font-medium">All families</TD>
                  <TD align="right" className="font-medium">{pct(cov80, lang, 1)}</TD>
                  <TD align="right" className="font-medium">{pct(cov95, lang, 1)}</TD>
                  <TD>{coverageLevel(cov80, 0.8) === "good" && coverageLevel(cov95, 0.95) === "good"
                    ? <StatusBadge level="good">Calibrated</StatusBadge> : <StatusBadge level="warning">Off target</StatusBadge>}</TD>
                </TR>
                {covFam.map((f) => {
                  const ok = coverageLevel(f["80"], 0.8) === "good" && coverageLevel(f["95"], 0.95) === "good";
                  return (
                    <TR key={f.family}>
                      <TD className="whitespace-nowrap">{f.family}</TD>
                      <TD align="right" title={pts(f["80"] - 0.8, lang)}>{pct(f["80"], lang, 1)}</TD>
                      <TD align="right" title={pts(f["95"] - 0.95, lang)}>{pct(f["95"], lang, 1)}</TD>
                      <TD>{ok ? <StatusBadge level="good">Calibrated</StatusBadge> : <StatusBadge level="warning">Off target</StatusBadge>}</TD>
                    </TR>
                  );
                })}
              </tbody>
            </Table>
          </CardBody>
        </Card>

        <Card className="self-start">
          <CardHeader title={"How the backtest works"}
            subtitle={"Each origin replays a real morning: the model never sees data from after it."} />
          <CardBody className="space-y-5">
            <div className="space-y-3 text-[13px] leading-relaxed text-ink-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <CalendarRange className="h-4 w-4 text-ink-3" />
                <span className="text-ink-3">{`${origins.length} origins:`}</span>
                {origins.map((o) => <Badge key={o} variant="neutral" className="tabular">{dateLabel(o, lang, { day: "numeric", month: "short", year: "numeric" })}</Badge>)}
              </div>
              <ul className="list-disc space-y-1.5 pl-5 marker:text-ink-3">
                <li>At each origin the model is retrained from scratch on data strictly before it, with the same pipeline as production (censoring EM, conformal intervals).</li>
                <li>Every day of the following weeks is forecast at every lead time from 1 to 7 days, as a real order would be.</li>
                <li>Observed metrics use uncensored days only (no stock-out, so sales equal demand) and exclude markdown days.</li>
                <li>Baselines: the stores’ current rule (a 2-week sales average times the chain’s weekday pattern, blended with the same weekday over the last 3 weeks, all from capped sales), seasonal naive (same day last week) and a 28-day moving average.</li>
              </ul>
              <p className="text-[12.5px] text-ink-3">{`${num(data.rows, lang)} (day, lead time) pairs evaluated.`}</p>
            </div>
            <div>
              <div className="mb-1 text-[12.5px] font-medium text-ink-2">WAPE by origin</div>
              <Table>
                <THead><TR><TH>Origin</TH>{METHODS.map((m) => <TH key={m} align="right">{shortLabel(m)}</TH>)}</TR></THead>
                <tbody>
                  {byOrigin.map((o) => (
                    <TR key={o.origin}>
                      <TD className="whitespace-nowrap tabular">{dateLabel(o.origin, lang, { day: "numeric", month: "short", year: "numeric" })}</TD>
                      {METHODS.map((m) => <TD key={m} align="right" className={m === "model" ? "font-medium" : "text-ink-2"}>{pct(o[m], lang, 1)}</TD>)}
                    </TR>
                  ))}
                </tbody>
              </Table>
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
