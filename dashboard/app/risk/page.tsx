"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, ChevronRight, PackageX, ShoppingCart, Store, Tag } from "lucide-react";
import { useHeatmap, useRecommendations } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { money, num, pct } from "@/lib/format";
import { PageHeader } from "@/components/ui/page";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { Segmented } from "@/components/ui/segmented";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { OrderBadge } from "@/components/domain/badges";
import { RankedBars, RiskHeatmap, type RiskCell, type RiskMetric } from "@/components/domain/risk-charts";
import { cn } from "@/lib/utils";

function StockoutTable() {
  const { t, lang } = useI18n();
  const router = useRouter();
  const { data, isLoading, error } = useRecommendations({ action: "STOCKOUT", sort: "p_stockout" });
  const rows = (data?.items ?? []).slice(0, 15);
  return (
    <Card>
      <CardHeader
        title={"Stock-out alerts"}
        subtitle={data
          ? (`${num(data.total, lang)} store-SKUs have a ≥ 30% chance of running out before the next delivery. The 15 most exposed:`)
          : "Products most likely to run out before the next delivery"}
        actions={<Link href="/recommendations?action=STOCKOUT" className="text-[13px] font-medium text-brand hover:underline">View all →</Link>}
      />
      <CardBody className="px-2">
        {error ? <ErrorState error={error} /> : isLoading ? <Loading rows={4} /> : rows.length === 0 ? <Empty>No stock-out alerts</Empty> : (
          <Table>
            <THead>
              <TR>
                <TH>{t("rec.col.product")}</TH>
                <TH>{t("top.store")}</TH>
                <TH align="right">On hand · forecast today</TH>
                <TH align="right">P(stock-out)</TH>
                <TH>Next order (ref. → rec.)</TH>
                <TH />
              </TR>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TR key={`${r.store_id}-${r.sku_id}`} className="cursor-pointer hover:bg-surface-2" onClick={() => router.push(`/item/${r.store_id}/${r.sku_id}`)}>
                  <TD className="min-w-[180px]">
                    <Link prefetch={false} href={`/item/${r.store_id}/${r.sku_id}`} className="font-medium hover:underline" onClick={(e) => e.stopPropagation()}>{r.product_name}</Link>
                    <div className="text-[12px] text-ink-3">{r.family}</div>
                  </TD>
                  <TD className="min-w-[120px] text-ink-2">{r.store_name}</TD>
                  <TD align="right" className="text-ink-2">{num(r.stock_on_hand, lang)} · {num(r.forecast_today, lang, 1)}</TD>
                  <TD align="right">
                    <div className="flex items-center justify-end gap-2">
                      <div className="hidden h-1.5 w-14 overflow-hidden rounded-full bg-surface-2 sm:block" aria-hidden>
                        <div className="h-full rounded-full bg-[var(--seq-500)]" style={{ width: `${Math.round(r.p_stockout * 100)}%` }} />
                      </div>
                      <span className="w-10 font-medium">{pct(r.p_stockout, lang)}</span>
                    </div>
                  </TD>
                  <TD><OrderBadge action={r.order_action} reference={r.order_reference} recommended={r.order_recommended} /></TD>
                  <TD className="w-6"><ChevronRight className="h-4 w-4 text-ink-3" /></TD>
                </TR>
              ))}
            </tbody>
          </Table>
        )}
      </CardBody>
    </Card>
  );
}

export default function RiskPage() {
  const { t, lang } = useI18n();
  const router = useRouter();
  const { data, isLoading, error } = useHeatmap();
  const [metric, setMetric] = useState<RiskMetric>("at_risk");
  const [view, setView] = useState<"chart" | "table">("chart");

  const metricLabels: Record<RiskMetric, string> = useMemo(() => ({
    at_risk: "Expected waste if nothing is done",
    stockout_alerts: "Stock-out alerts",
    markdowns: "Targeted markdowns",
  }), []);
  const format = useCallback((m: RiskMetric, v: number) => (m === "at_risk" ? money(v, lang) : num(v, lang)), [lang]);

  const cells: RiskCell[] = useMemo(() => data?.cells ?? [], [data]);
  const agg = useMemo(() => {
    const byStore = new Map<number, { store_id: number; store_name: string; v: Record<RiskMetric, number>; items: number }>();
    const byFamily = new Map<string, { family: string; v: Record<RiskMetric, number>; items: number }>();
    const total: Record<RiskMetric, number> = { at_risk: 0, stockout_alerts: 0, markdowns: 0 };
    let items = 0;
    for (const c of cells) {
      const s = byStore.get(c.store_id) ?? { store_id: c.store_id, store_name: c.store_name, v: { at_risk: 0, stockout_alerts: 0, markdowns: 0 }, items: 0 };
      const f = byFamily.get(c.family) ?? { family: c.family, v: { at_risk: 0, stockout_alerts: 0, markdowns: 0 }, items: 0 };
      (["at_risk", "stockout_alerts", "markdowns"] as RiskMetric[]).forEach((m) => { s.v[m] += c[m]; f.v[m] += c[m]; total[m] += c[m]; });
      s.items += c.items; f.items += c.items; items += c.items;
      byStore.set(c.store_id, s); byFamily.set(c.family, f);
    }
    return { stores: [...byStore.values()], families: [...byFamily.values()], total, items };
  }, [cells]);

  const storeOrder = useMemo(() => {
    const known = new Map(agg.stores.map((s) => [s.store_id, s]));
    const base: { store_id: number; store_name: string }[] = data?.stores ?? agg.stores;
    return [...base].sort((a, b) => (known.get(b.store_id)?.v[metric] ?? 0) - (known.get(a.store_id)?.v[metric] ?? 0) || a.store_id - b.store_id);
  }, [data, agg, metric]);
  const familyOrder = useMemo(() => {
    const known = new Map(agg.families.map((f) => [f.family, f]));
    const base: string[] = data?.families ?? agg.families.map((f) => f.family);
    return [...base].sort((a, b) => (known.get(b)?.v[metric] ?? 0) - (known.get(a)?.v[metric] ?? 0) || a.localeCompare(b));
  }, [data, agg, metric]);

  const topStores = useMemo(() => [...agg.stores].sort((a, b) => b.v[metric] - a.v[metric]).slice(0, 5), [agg, metric]);
  const topFamilies = useMemo(() => [...agg.families].sort((a, b) => b.v[metric] - a.v[metric]).slice(0, 5), [agg, metric]);
  const share = (rows: { v: Record<RiskMetric, number> }[]) => (agg.total[metric] > 0 ? rows.reduce((a, r) => a + r.v[metric], 0) / agg.total[metric] : 0);
  const riskTop5 = useMemo(() => {
    const top = [...agg.stores].sort((a, b) => b.v.at_risk - a.v.at_risk).slice(0, 5);
    return agg.total.at_risk > 0 ? top.reduce((a, s) => a + s.v.at_risk, 0) / agg.total.at_risk : 0;
  }, [agg]);

  const openCell = useCallback((c: RiskCell) => router.push(`/recommendations?store=${c.store_id}&family=${encodeURIComponent(c.family)}&only=1`), [router]);

  if (isLoading) return <Loading rows={6} />;
  if (error) return <ErrorState error={error} />;

  const metricHelp: Record<RiskMetric, string> = {
    at_risk: "Cost value of the units that would be thrown away if nothing is done.",
    stockout_alerts: "Products with a ≥ 30% chance of running out before the next delivery.",
    markdowns: "Markdowns the engine recommends this morning.",
  };
  const unitWord = (m: RiskMetric) => (m === "at_risk" ? "of the total" : m === "stockout_alerts" ? "of all alerts" : "of all markdowns");

  return (
    <div className="space-y-6">
      <PageHeader title={t("risk.title")} subtitle={t("risk.subtitle")}
        actions={<Link href="/recommendations?only=1" className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand px-3.5 text-[13px] font-medium text-brand-ink hover:opacity-90">{t("nav.recommendations")}<ArrowRight className="h-4 w-4" /></Link>} />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat icon={<PackageX className="h-4 w-4" />} label={metricLabels.at_risk} value={money(agg.total.at_risk, lang)} hint={metricHelp.at_risk}
          delta={`${num(agg.items, lang)} store-SKUs scored`} />
        <Stat icon={<ShoppingCart className="h-4 w-4" />} label={metricLabels.stockout_alerts} value={num(agg.total.stockout_alerts, lang)} hint={metricHelp.stockout_alerts}
          delta={"≥ 30% risk before next delivery"} />
        <Stat icon={<Tag className="h-4 w-4" />} label={metricLabels.markdowns} value={num(agg.total.markdowns, lang)} hint={metricHelp.markdowns}
          delta={"proposed this morning"} />
        <Stat icon={<Store className="h-4 w-4" />} label={"Share of risk in the 5 most exposed stores"}
          value={pct(riskTop5, lang)} delta={`of ${num(agg.stores.length, lang)} stores`} />
      </div>

      <Card>
        <CardHeader
          title={"Where the risk sits"}
          subtitle={`${metricHelp[metric]} Rows and columns sorted by total (scale below the map). Click a cell to open its actions.`}
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Segmented value={metric} onChange={setMetric} size="sm" options={[
                { value: "at_risk", label: "Expected waste ($)" },
                { value: "stockout_alerts", label: "Stock-out alerts" },
                { value: "markdowns", label: "Markdowns" },
              ]} />
              <Segmented value={view} onChange={setView} size="sm" options={[{ value: "chart", label: t("common.chart") }, { value: "table", label: t("common.table") }]} />
            </div>
          }
        />
        <CardBody>
          {cells.length === 0 ? <Empty /> : view === "chart" ? (
            <RiskHeatmap cells={cells} storeOrder={storeOrder} familyOrder={familyOrder} metric={metric} format={format} metricLabels={metricLabels} onCell={openCell} />
          ) : (
            <Table className="max-h-[640px]">
              <THead>
                <TR>
                  <TH className="sticky left-0 z-10 bg-surface">{t("top.store")}</TH>
                  {familyOrder.map((f) => <TH key={f} align="right">{f}</TH>)}
                  <TH align="right">Total</TH>
                </TR>
              </THead>
              <tbody>
                {storeOrder.map((s) => {
                  const row = cells.filter((c) => c.store_id === s.store_id);
                  return (
                    <TR key={s.store_id}>
                      <TD className="sticky left-0 whitespace-nowrap bg-surface font-medium">{s.store_name}</TD>
                      {familyOrder.map((f) => {
                        const c = row.find((x) => x.family === f);
                        return (
                          <TD key={f} align="right" className={cn(c ? "cursor-pointer hover:bg-surface-2" : "text-ink-3", c && !c[metric] && "text-ink-3")} onClick={c ? () => openCell(c) : undefined}>
                            {c ? format(metric, c[metric]) : "–"}
                          </TD>
                        );
                      })}
                      <TD align="right" className="font-semibold">{format(metric, row.reduce((a, c) => a + c[metric], 0))}</TD>
                    </TR>
                  );
                })}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader title={"Top 5 stores"}
              subtitle={`${metricLabels[metric]} · ${pct(share(topStores), lang)} ${unitWord(metric)}`} />
            <CardBody>
              {topStores.length === 0 ? <Empty /> : (
                <RankedBars ariaLabel="Top 5 stores"
                  rows={topStores.map((s) => ({ key: String(s.store_id), name: s.store_name, value: s.v[metric], sub: `${num(s.items, lang)} products` }))}
                  format={(v) => format(metric, v)} onClick={(id) => router.push(`/recommendations?store=${id}&only=1`)} />
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={"Top 5 families"}
              subtitle={`${metricLabels[metric]} · ${pct(share(topFamilies), lang)} ${unitWord(metric)}`} />
            <CardBody>
              {topFamilies.length === 0 ? <Empty /> : (
                <RankedBars ariaLabel="Top 5 families"
                  rows={topFamilies.map((f) => ({ key: f.family, name: f.family, value: f.v[metric], sub: `${num(f.items, lang)} store-SKUs` }))}
                  format={(v) => format(metric, v)} onClick={(fam) => router.push(`/recommendations?family=${encodeURIComponent(fam)}&only=1`)} />
              )}
            </CardBody>
          </Card>
      </div>
      <StockoutTable />
      <p className="text-[12px] text-ink-3">
        Values come from this morning’s Monte Carlo run (demand paths × shelf lots by expiry date).
      </p>
    </div>
  );
}
