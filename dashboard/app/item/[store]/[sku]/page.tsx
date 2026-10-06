"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, Ban, Check, PencilLine, ShieldCheck, Tag, Truck, HandHeart } from "lucide-react";
import { toast } from "sonner";
import { useDecide, useItem, useMeta } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { dateLabel, money, num, pct } from "@/lib/format";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { ErrorState, Loading } from "@/components/ui/states";
import { ActionBadge, ConfidenceBadge } from "@/components/domain/badges";
import { ReasonList } from "@/components/domain/reasons";
import { ForecastChart, LotsChart, WasteDistChart } from "@/components/domain/item-charts";
import { WhatIf } from "@/components/domain/whatif";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

const BLOCK_LABEL: Record<string, string> = {
  PROMO_LOCK: "Promo lock", MAX_DISCOUNT: "Max discount", UNIT_MARGIN_FLOOR: "Unit margin floor",
  WINDOW_MARGIN_FLOOR: "Window margin floor", NOT_PROFITABLE: "Doesn't pay for itself",
};
const FACTOR_LABEL: Record<string, string> = {
  forecast_precision: "Forecast precision", history_length: "History length",
  expiry_data: "Expiry data quality", price_response: "Price-response evidence",
};

function Headline({ rec, lang }: { rec: any; lang: "en" }) {
  if (rec.action === "MARKDOWN")
    return (
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand"><Tag className="h-5 w-5" /></div>
        <div>
          <div className="text-[19px] font-semibold leading-snug tracking-tight text-ink">
            {`Label ${rec.units_to_label} units at -${Math.round(rec.discount_pct)}%`}
          </div>
          <div className="text-[13.5px] text-ink-2">
            {`Units expiring within ${rec.markdown_window_days} day${rec.markdown_window_days > 1 ? "s" : ""} · `}
            {money(rec.regular_price, lang, 2)} → <b className="text-ink">{money(rec.new_price, lang, 2)}</b>
          </div>
        </div>
      </div>
    );
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-ink-2"><ShieldCheck className="h-5 w-5" /></div>
      <div>
        <div className="text-[19px] font-semibold leading-snug tracking-tight text-ink">No markdown today</div>
        <div className="text-[13.5px] text-ink-2">Keep the regular price · {money(rec.regular_price, lang, 2)}</div>
      </div>
    </div>
  );
}

function Compare({ label, legacy, none, engine, lang, better = "lower" }: { label: string; legacy: number; none: number; engine: number; lang: "en"; better?: "lower" | "higher" }) {
  const d = engine - legacy;
  const good = better === "lower" ? d < -0.005 : d > 0.005;
  return (
    <div className="rounded-lg border border-border px-3 py-2.5">
      <div className="text-[12px] text-ink-3">{label}</div>
      <div className="mt-1 flex items-baseline gap-2"><span className="text-[18px] font-semibold tabular">{money(engine, lang, 2)}</span>
        <span className={cn("text-[12px] tabular", Math.abs(d) < 0.005 ? "text-ink-3" : good ? "text-good-ink" : "text-critical-ink")}>{d > 0 ? "+" : ""}{money(d, lang, 2)} vs current rule</span></div>
      <div className="mt-0.5 text-[11.5px] text-ink-3 tabular">Current rule {money(legacy, lang, 2)} · No action {money(none, lang, 2)}</div>
    </div>
  );
}

export default function ItemPage() {
  const params = useParams<{ store: string; sku: string }>();
  const store = Number(params.store), sku = Number(params.sku);
  const { t, lang } = useI18n();
  const { data, isLoading, error } = useItem(store, sku);
  const { data: meta } = useMeta();
  const decide = useDecide();
  const [note, setNote] = useState("");
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overridePct, setOverridePct] = useState(20);

  if (isLoading) return <Loading rows={6} />;
  if (error) return <ErrorState error={error} />;
  const rec = data.recommendation;
  const el = data.elasticity?.sku?.[0];

  const submit = (decision: "ACCEPTED" | "OVERRIDDEN" | "REJECTED") => {
    const body: any = { store_id: store, sku_id: sku, decision, note };
    if (decision === "OVERRIDDEN") { body.applied_action = overridePct > 0 ? "MARKDOWN" : "NO_ACTION"; body.applied_discount_pct = overridePct; }
    decide.mutate(body, { onSuccess: () => { toast.success(t("item.logged")); setNote(""); setOverrideOpen(false); } });
  };

  return (
    <div className="space-y-6">
      <div>
        <Link href={`/recommendations?store=${store}&only=1`} className="inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink"><ArrowLeft className="h-4 w-4" />{t("item.back")}</Link>
        <div className="mt-2 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-[24px] font-semibold tracking-tight">{rec.product_name}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-ink-3">
              <span>{rec.subfamily && rec.subfamily !== rec.family ? `${rec.family} · ${rec.subfamily}` : rec.family}</span><span>·</span><span>{rec.store_name}</span><span>·</span><span className="tabular">UPC {rec.upc}</span>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <ActionBadge action={rec.action} discount={rec.discount_pct} />
            <ConfidenceBadge tier={rec.confidence_tier} />
            {rec.explored && <Badge variant="outline">Exploration</Badge>}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title={t("item.why")} subtitle={meta ? `Decision for ${dateLabel(meta.as_of_date, lang, { weekday: "long", day: "numeric", month: "long" })}` : undefined} />
          <CardBody className="space-y-5">
            <Headline rec={rec} lang={lang} />
            {(rec.order_action !== "KEEP" || rec.donate_units > 0) && (
              <div className="flex flex-wrap gap-2">
                {rec.order_action !== "KEEP" && (
                  <div className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface-2/60 px-3 py-2 text-[13px]">
                    <Truck className="h-4 w-4 text-ink-3" />{t(`order.${rec.order_action}`)}: <span className="tabular">{num(rec.order_reference, lang)} → <b>{num(rec.order_recommended, lang)}</b></span>
                    <span className="text-ink-3">(service level {pct(rec.service_level, lang)})</span>
                  </div>
                )}
                {rec.donate_units > 0 && <div className="inline-flex items-center gap-2 rounded-lg border border-border bg-good-soft px-3 py-2 text-[13px] text-good-ink"><HandHeart className="h-4 w-4" />{t("action.DONATE")}: ~{rec.donate_units} {t("common.units")}</div>}
              </div>
            )}
            <ReasonList reasons={rec.reason_codes} />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Compare label={"Expected waste (at cost)"} legacy={rec.legacy_waste_value} none={rec.baseline_waste_value} engine={rec.expected_waste_value} lang={lang} />
              <Compare label={"Margin after waste (7 days)"} legacy={rec.legacy_net_margin} none={rec.baseline_net_margin} engine={rec.expected_net_margin} lang={lang} better="higher" />
            </div>
          </CardBody>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader title={t("item.decision")} subtitle={"Logged and fed back into retraining"} />
            <CardBody className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={() => submit("ACCEPTED")} disabled={decide.isPending}><Check className="h-4 w-4" />{t("item.accept")}</Button>
                <Button variant="outline" onClick={() => setOverrideOpen((o) => !o)}><PencilLine className="h-4 w-4" />{t("item.override")}</Button>
                <Button variant="ghost" onClick={() => submit("REJECTED")} disabled={decide.isPending}><Ban className="h-4 w-4" />{t("item.reject")}</Button>
              </div>
              {overrideOpen && (
                <div className="flex items-center gap-2 rounded-lg bg-surface-2/60 p-2 text-[13px]">
                  <span className="text-ink-2">{t("item.discount")}</span>
                  <select value={overridePct} onChange={(e) => setOverridePct(Number(e.target.value))} className="h-8 rounded-md border border-border-strong bg-surface px-2">
                    {[0, 10, 20, 30, 40, 50].map((v) => <option key={v} value={v}>{v === 0 ? t("action.NO_ACTION") : `-${v}%`}</option>)}
                  </select>
                  <Button size="sm" variant="primary" onClick={() => submit("OVERRIDDEN")}>OK</Button>
                </div>
              )}
              <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("item.note")} className="h-9 w-full rounded-lg border border-border-strong bg-surface px-3 text-[13px]" />
              {data.decisions.length > 0 && (
                <ul className="space-y-1.5 border-t border-border pt-3 text-[12.5px]">
                  {data.decisions.slice(0, 4).map((d: any, i: number) => (
                    <li key={i} className="flex items-center justify-between gap-2"><Badge variant={d.decision === "ACCEPTED" ? "good" : d.decision === "REJECTED" ? "critical" : "warning"}>{d.decision}</Badge>
                      <span className="truncate text-ink-3">{d.user} · {d.created_at?.slice(11, 16)}{d.note ? ` · ${d.note}` : ""}</span></li>
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title={t("item.confidenceWhy")} subtitle={`Score ${num(rec.confidence_score, lang, 2)}`} />
            <CardBody className="space-y-2.5">
              {rec.confidence_factors.map((f: any) => (
                <div key={f.factor}>
                  <div className="flex justify-between text-[12.5px]"><span className="text-ink-2">{(FACTOR_LABEL[f.factor] ?? f.factor)}</span><span className="tabular text-ink-3">{num(f.score, lang, 2)}</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-[color-mix(in_oklab,var(--series-1)_18%,transparent)]"><div className="h-full rounded-full bg-[var(--series-1)]" style={{ width: `${f.score * 100}%` }} /></div>
                </div>
              ))}
              {el && (
                <div className="mt-3 border-t border-border pt-3 text-[12.5px] text-ink-2">
                  <div className="font-medium text-ink">{t("item.elasticity")}</div>
                  <div className="tabular">ε = {num(el.mean, lang, 2)} <span className="text-ink-3">(94% HDI {num(el.hdi_low, lang, 2)}–{num(el.hdi_high, lang, 2)})</span></div>
                  <div className="text-ink-3">{el.source === "posterior" ? "Measured in the price test" : "Borrowed from the family"}</div>
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader title={t("item.history")} subtitle={"Stock-out days are censored demand: true demand was at least the sales shown."} />
        <CardBody><ForecastChart history={data.history} forecast={data.forecast} /></CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader title={t("item.lots")} subtitle={"Orange: units inside the markdown window"} />
          <CardBody>
            {meta && <LotsChart lots={data.lots} asOf={meta.as_of_date} windowDays={rec.action === "MARKDOWN" ? rec.markdown_window_days : 3} />}
            <div className="mt-2 flex flex-wrap gap-2 text-[12px] text-ink-3">
              {data.lots.some((l: any) => l.is_expiry_imputed) && <Badge variant="warning">Expiry estimated (not tracked)</Badge>}
              {data.lots.some((l: any) => l.is_inbound) && <Badge variant="outline">Includes today’s delivery</Badge>}
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t("item.unsold")} subtitle={"Monte Carlo distribution for this morning's stock"} />
          <CardBody><WasteDistChart baseline={data.waste_hist_baseline} chosen={rec.action === "MARKDOWN" ? data.waste_hist_chosen : undefined} labels={[t("item.noAction"), "Recommendation"]} /></CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={t("item.candidates")} subtitle={"Objective: lowest expected waste without breaking a rule; at equal waste, the best margin."} />
        <CardBody className="px-2">
          <Table>
            <THead><TR><TH>{t("rec.col.action")}</TH><TH align="right">Price</TH><TH align="right">Waste (units)</TH><TH align="right">Waste ($)</TH><TH align="right">P(waste)</TH><TH align="right">Revenue</TH><TH align="right">Margin after waste</TH><TH align="right">Window margin</TH><TH>Status</TH></TR></THead>
            <tbody>
              {data.candidates.map((c: any, i: number) => (
                <TR key={i} className={cn(c.chosen && "bg-brand-soft/60")}>
                  <TD>{c.action === "NO_ACTION" ? <span className="text-ink-2">{t("item.noAction")}</span> : <span className="tabular">-{Math.round(c.discount_pct)}% · ≤{c.window_days}d</span>}</TD>
                  <TD align="right">{money(c.new_price, lang, 2)}</TD><TD align="right">{num(c.waste_units, lang, 1)}</TD><TD align="right">{money(c.waste_value, lang, 2)}</TD>
                  <TD align="right">{pct(c.p_waste, lang)}</TD><TD align="right">{money(c.revenue, lang)}</TD><TD align="right">{money(c.net_margin ?? c.margin - c.waste_value, lang)}</TD>
                  <TD align="right">{c.action === "NO_ACTION" ? "–" : pct(c.window_margin_rate, lang)}</TD>
                  <TD>{c.chosen ? <Badge variant="brand" icon={<Check className="h-3 w-3" />}>{t("item.chosen")}</Badge> : c.blocked_by ? <Badge variant="critical">{(BLOCK_LABEL[c.blocked_by] ?? c.blocked_by)}</Badge> : <span className="text-[12px] text-ink-3">Feasible</span>}</TD>
                </TR>
              ))}
            </tbody>
          </Table>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("item.whatif")} subtitle={"Test another discount: same engine, same rules, simulated on demand."} />
        <CardBody><WhatIf storeId={store} skuId={sku} initialDiscount={rec.discount_pct} initialWindow={rec.markdown_window_days} /></CardBody>
      </Card>
    </div>
  );
}
