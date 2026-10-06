"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback } from "react";
import { ArrowRight, HandHeart, PackageX, ShoppingCart, Tag, TrendingDown, Truck } from "lucide-react";
import type { EChartsOption } from "echarts";
import { useOverview } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { money, moneyCompact, num, pct, dateLabel } from "@/lib/format";
import { PageHeader } from "@/components/ui/page";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { Badge } from "@/components/ui/badge";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { ErrorState, Loading } from "@/components/ui/states";
import { EChart, axisStyle, baseOption, type Tokens } from "@/components/charts/echart";
import { ActionBadge, ConfidenceBadge, DonateBadge, OrderBadge } from "@/components/domain/badges";

/* eslint-disable @typescript-eslint/no-explicit-any */

function TrendChart({ data, field, title, format, pilot }: { data: any[]; field: string; title: string; format: (v: number) => string; pilot?: { start?: string; end?: string } }) {
  const { lang } = useI18n();
  const option = useCallback((t: Tokens): EChartsOption => ({
    ...baseOption(t),
    grid: { left: 4, right: 12, top: 12, bottom: 4, containLabel: true },
    tooltip: { ...baseOption(t).tooltip as object, trigger: "axis", axisPointer: { type: "line", lineStyle: { color: t.axis } },
      formatter: (p: any) => `<div style="color:${t["ink-3"]};font-size:11px">${dateLabel(p[0].axisValue, lang, { day: "numeric", month: "short", year: "numeric" })}</div><div style="font-weight:600;font-size:13px">${format(p[0].value)}</div>` },
    xAxis: { type: "category", data: data.map((d) => d.week_start), boundaryGap: false, ...axisStyle(t), splitLine: { show: false },
      axisLabel: { ...axisStyle(t).axisLabel, formatter: (v: string) => dateLabel(v, lang), interval: Math.ceil(data.length / 5) } },
    yAxis: { type: "value", scale: true, ...axisStyle(t), axisLabel: { ...axisStyle(t).axisLabel, formatter: (v: number) => format(v) }, splitNumber: 3 },
    series: [{
      type: "line", data: data.map((d) => d[field]), showSymbol: false, smooth: 0.25,
      lineStyle: { width: 2, color: t["series-1"] }, itemStyle: { color: t["series-1"] },
      areaStyle: { color: t["series-1"], opacity: 0.08 },
      markArea: pilot?.start && data.length && pilot.start >= data[0].week_start && pilot.start <= data[data.length - 1].week_start ? { silent: true, itemStyle: { color: t["surface-2"], opacity: 0.9 },
        label: { show: true, position: "insideTop", color: t["ink-3"], fontSize: 10.5, formatter: "Pilot" },
        data: [[{ xAxis: data.find((d) => d.week_start >= pilot.start!)?.week_start }, { xAxis: data.filter((d) => d.week_start <= (pilot.end ?? "")).at(-1)?.week_start }]] } : undefined,
    }],
  }), [data, field, format, lang, pilot]);
  return (
    <div>
      <div className="mb-1 text-[12.5px] font-medium text-ink-2">{title}</div>
      <EChart option={option} height={150} ariaLabel={title} />
    </div>
  );
}

function FamilyBars({ data }: { data: any[] }) {
  const { lang } = useI18n();
  const rows = [...data].sort((a, b) => a.legacy_waste - b.legacy_waste);
  const option = useCallback((t: Tokens): EChartsOption => ({
    ...baseOption(t),
    grid: { left: 4, right: 48, top: 30, bottom: 4, containLabel: true },
    legend: { ...baseOption(t).legend as object, data: ["Current rule", "Perisentra"], itemGap: 20 },
    tooltip: { ...baseOption(t).tooltip as object, trigger: "axis", axisPointer: { type: "shadow", shadowStyle: { color: t["surface-2"] } },
      valueFormatter: (v: any) => money(v, lang) },
    xAxis: { type: "value", splitNumber: 3, ...axisStyle(t), axisLabel: { ...axisStyle(t).axisLabel, formatter: (v: number) => moneyCompact(v, lang) } },
    yAxis: { type: "category", data: rows.map((r) => r.family), ...axisStyle(t), splitLine: { show: false } },
    series: [
      { name: "Current rule", type: "bar", data: rows.map((r) => r.legacy_waste), barWidth: 8, barGap: "40%",
        itemStyle: { color: t["muted-series"], borderRadius: [0, 4, 4, 0] } },
      { name: "Perisentra", type: "bar", data: rows.map((r) => r.expected_waste), barWidth: 8,
        itemStyle: { color: t["series-1"], borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right", color: t["ink-2"], fontSize: 11, formatter: (p: any) => moneyCompact(p.value, lang) } },
    ],
  }), [rows, lang]);
  return <EChart option={option} height={Math.max(260, rows.length * 30 + 40)} ariaLabel="Expected waste by family" />;
}

export default function OverviewPage() {
  const { t, lang } = useI18n();
  const router = useRouter();
  const { data, isLoading, error } = useOverview();
  if (isLoading) return <Loading rows={5} />;
  if (error) return <ErrorState error={error} />;
  const k = data.kpi;
  const wasteCut = k.legacy_waste > 0 ? k.waste_vs_legacy / k.legacy_waste : 0;
  const tiers = data.confidence_tiers as Record<string, number>;
  const tierTotal = Object.values(tiers).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-6">
      <PageHeader eyebrow={dateLabel(data.meta.as_of_date, lang, { weekday: "long", day: "numeric", month: "long" })} title={t("ov.title")} subtitle={t("ov.subtitle")}
        actions={<Link href="/recommendations?only=1" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand px-3.5 text-[13px] font-medium text-brand-ink hover:opacity-90">{t("nav.recommendations")}<ArrowRight className="h-4 w-4" /></Link>} />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-6">
        <Stat accent className="xl:col-span-2" icon={<TrendingDown className="h-4 w-4" />} label="Waste avoided vs the current markdown rule"
          value={money(k.waste_vs_legacy, lang)}
          delta={`${pct(wasteCut, lang)} less waste · margin after waste ${k.net_margin_vs_legacy >= 0 ? "+" : ""}${money(k.net_margin_vs_legacy, lang)}`} />
        <Stat icon={<PackageX className="h-4 w-4" />} label={t("ov.atRisk")} value={money(k.stock_at_risk, lang)} hint={t("ov.atRiskHint")}
          delta={`${num(k.items, lang)} store-SKUs scored`} />
        <Stat icon={<Tag className="h-4 w-4" />} label={t("ov.markdowns")} value={num(k.markdowns, lang)} deltaTone="good"
          delta={t("ov.vsLegacy", { n: num(k.legacy_markdowns, lang) })} />
        <Stat icon={<Truck className="h-4 w-4" />} label={t("ov.orders")} value={num(k.order_changes, lang)}
          delta={`↓ ${num(k.order_reduce, lang)} · ↑ ${num(k.order_increase, lang)}`} />
        <Stat icon={<ShoppingCart className="h-4 w-4" />} label={t("ov.stockouts")} value={num(k.stockout_alerts, lang)}
          delta={<span className="inline-flex items-center gap-1"><HandHeart className="h-3.5 w-3.5" />{num(k.donations, lang)} {t("ov.donations").toLowerCase()}</span>} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title={t("ov.trend")} subtitle={"Whole chain. Shaded: pilot in 6 stores."} />
          <CardBody className="grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            <TrendChart data={data.weekly} field="waste_value" title={t("ov.wasteTrend")} format={(v) => moneyCompact(v, lang)} pilot={data.pilot} />
            <TrendChart data={data.weekly} field="markdown_events" title={t("ov.mdTrend")} format={(v) => num(v, lang)} pilot={data.pilot} />
            <TrendChart data={data.weekly} field="margin_rate" title={t("ov.marginTrend")} format={(v) => pct(v, lang, 1)} pilot={data.pilot} />
            <TrendChart data={data.weekly} field="stockout_rate" title={t("ov.stockoutTrend")} format={(v) => pct(v, lang, 1)} pilot={data.pilot} />
          </CardBody>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader title={"Expected waste by family"} subtitle={"This morning's stock: current rule vs Perisentra"} />
          <CardBody><FamilyBars data={data.by_family} /></CardBody>
        </Card>
      </div>

        <Card>
          <CardHeader title={t("ov.topRisk")} actions={<Link href="/recommendations" className="text-[13px] font-medium text-brand hover:underline">{t("nav.recommendations")} →</Link>} />
          <CardBody className="px-2">
            <Table>
              <THead><TR><TH>{t("rec.col.product")}</TH><TH>{t("top.store")}</TH><TH align="right">{t("rec.col.expiring")}</TH><TH align="right">{t("rec.col.risk")}</TH><TH>{t("rec.col.action")}</TH><TH>{t("rec.col.order")}</TH><TH align="right">{t("rec.col.avoided")}</TH><TH>{t("rec.col.confidence")}</TH></TR></THead>
              <tbody>
                {data.top_at_risk.map((r: any) => (
                  <TR key={`${r.store_id}-${r.sku_id}`} className="cursor-pointer hover:bg-surface-2" tabIndex={0} onClick={() => router.push(`/item/${r.store_id}/${r.sku_id}`)} onKeyDown={(e) => e.key === "Enter" && router.push(`/item/${r.store_id}/${r.sku_id}`)}>
                    <TD className="min-w-[190px]"><div className="font-medium">{r.product_name}</div><div className="text-[12px] text-ink-3">{r.family}</div></TD>
                    <TD className="min-w-[120px] text-ink-2">{r.store_name}</TD>
                    <TD align="right">{num(r.units_expiring_3d, lang)}</TD>
                    <TD align="right"><div>{money(r.baseline_waste_value, lang)}</div><div className="text-[11.5px] text-ink-3">{pct(r.p_waste_baseline, lang)}</div></TD>
                    <TD><div className="flex flex-col items-start gap-1"><ActionBadge action={r.action} discount={r.discount_pct} /><DonateBadge units={r.donate_units} /></div></TD>
                    <TD><OrderBadge action={r.order_action} reference={r.order_reference} recommended={r.order_recommended} /></TD>
                    <TD align="right" className="text-good-ink">{money(r.waste_avoided_value, lang)}</TD>
                    <TD><ConfidenceBadge tier={r.confidence_tier} short /></TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          </CardBody>
        </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title={t("ov.byStore")} subtitle={"Waste avoided vs current rule"} />
          <CardBody className="px-2">
            <Table className="max-h-[440px]">
              <THead><TR><TH>{t("top.store")}</TH><TH align="right">{t("ov.markdowns")}</TH><TH align="right">Avoided</TH></TR></THead>
              <tbody>
                {data.by_store.map((s: any) => (
                  <TR key={s.store_id} className="cursor-pointer hover:bg-surface-2" tabIndex={0} onClick={() => router.push(`/recommendations?store=${s.store_id}&only=1`)} onKeyDown={(e) => e.key === "Enter" && router.push(`/recommendations?store=${s.store_id}&only=1`)}>
                    <TD>
                      <div className="flex items-center gap-1.5 font-medium">{s.store_name}
                        {s.pilot_group === "pilot" && <Badge variant="brand">Pilot</Badge>}
                        {s.pilot_group === "control" && <Badge variant="outline">Control</Badge>}
                      </div>
                      <div className="text-[12px] capitalize text-ink-3">{s.store_format} · {s.city}</div>
                    </TD>
                    <TD align="right">{num(s.markdowns, lang)}</TD>
                    <TD align="right" className="text-good-ink">{money(s.vs_legacy, lang)}</TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          </CardBody>
        </Card>
        <Card className="self-start xl:col-span-2">
          <CardHeader title={t("ov.confidence")} subtitle={"Based on forecast precision, history length, expiry data quality and price-response evidence"} />
          <CardBody>
            <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-2" role="img" aria-label="Confidence mix">
              {(["HIGH", "MEDIUM", "LOW"] as const).map((tier, i) => (
                <div key={tier} style={{ width: `${(100 * (tiers[tier] ?? 0)) / tierTotal}%`, background: ["var(--good)", "var(--warning)", "var(--critical)"][i] }} className="h-full border-r-2 border-surface last:border-0" />
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-4 text-[13px]">
              {(["HIGH", "MEDIUM", "LOW"] as const).map((tier) => (
                <div key={tier} className="flex items-center gap-2"><ConfidenceBadge tier={tier} /><span className="tabular text-ink-2">{num(tiers[tier] ?? 0, lang)} · {pct((tiers[tier] ?? 0) / tierTotal, lang)}</span></div>
              ))}
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
