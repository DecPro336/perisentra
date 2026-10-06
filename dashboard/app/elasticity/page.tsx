"use client";

import { useMemo, useState, type ReactNode } from "react";
import { ArrowRight, CircleAlert, CircleCheck, Clock, Network, Shuffle } from "lucide-react";
import { useElasticity, useMeta } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { dateLabel, num, pct } from "@/lib/format";
import type { Lang } from "@/lib/format";
import { PageHeader } from "@/components/ui/page";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
import { Segmented } from "@/components/ui/segmented";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { FamilyIntervalChart, SkuPrecisionScatter, type FamilyElasticity, type SkuElasticity } from "@/components/domain/elasticity-charts";
import { cn } from "@/lib/utils";

const lift = (d: number, e: number | null | undefined) => (e == null ? null : Math.pow(1 - d, -e) - 1);
const signedPct = (v: number | null, lang: Lang) => (v == null ? "–" : pct(v, lang, 0, true));
const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN);

function Step({ n, icon, title, children }: { n: number; icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex-1 rounded-lg border border-border bg-surface-2/50 p-4">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-surface text-[12px] font-semibold text-ink-2 ring-1 ring-border">{n}</span>
        <span className="text-ink-3">{icon}</span>
        <h3 className="text-[13.5px] font-semibold text-ink">{title}</h3>
      </div>
      <div className="mt-2 space-y-2 text-[13px] leading-relaxed text-ink-2">{children}</div>
    </div>
  );
}

function DiagTile({ label, value, note, status }: { label: string; value: ReactNode; note: ReactNode; status?: { ok: boolean; label: string } }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="text-[12.5px] font-medium text-ink-3">{label}</div>
        {status && (
          <Badge variant={status.ok ? "good" : "warning"} icon={status.ok ? <CircleCheck className="h-3 w-3" /> : <CircleAlert className="h-3 w-3" />}>{status.label}</Badge>
        )}
      </div>
      <div className="mt-1 text-[22px] font-semibold leading-tight tracking-tight text-ink">{value}</div>
      <div className="mt-1 text-[12px] leading-snug text-ink-3">{note}</div>
    </div>
  );
}

function LiftCalculator({ families }: { families: FamilyElasticity[] }) {
  const { lang } = useI18n();
  const sorted = useMemo(() => [...families].sort((a, b) => a.family.localeCompare(b.family)), [families]);
  const [fam, setFam] = useState(sorted[0]?.family ?? "");
  const [disc, setDisc] = useState("30");
  const row = sorted.find((r) => r.family === fam) ?? sorted[0];
  if (!row) return <Empty />;
  const d = Number(disc) / 100;
  const m = lift(d, row.mean), lo = lift(d, row.hdi_low), hi = lift(d, row.hdi_high), nv = lift(d, row.naive_elasticity);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select label={"Family"} value={row.family} onChange={(v) => v && setFam(v)} options={sorted.map((r) => ({ value: r.family, label: r.family }))} className="min-w-[230px]" />
        <Segmented value={disc} onChange={setDisc} size="sm" options={["10", "20", "30", "40", "50"].map((v) => ({ value: v, label: `-${v}%` }))} />
      </div>
      <div className="rounded-lg border border-border bg-surface-2/60 p-4">
        <div className="text-[12.5px] text-ink-3">Expected demand lift</div>
        <div className="mt-0.5 text-[30px] font-semibold leading-tight tracking-tight text-ink">{signedPct(m, lang)}</div>
        <p className="mt-1.5 text-[13px] leading-relaxed text-ink-2">
          {<>A <b className="text-ink">{disc}%</b> discount on <b className="text-ink">{row.family}</b> lifts expected demand by about <b className="text-ink">{signedPct(m, lang)}</b> (94% interval {signedPct(lo, lang)} to {signedPct(hi, lang)}). History alone would have predicted {signedPct(nv, lang)}.</>}
        </p>
      </div>
      <Table>
        <THead><TR><TH>Discount</TH><TH align="right">Expected lift</TH><TH align="right">94% interval</TH><TH align="right">Naive</TH></TR></THead>
        <tbody>
          {[0.1, 0.2, 0.3, 0.4, 0.5].map((x) => (
            <TR key={x} className={cn("cursor-pointer", Math.round(x * 100) === Number(disc) ? "bg-surface-2" : "hover:bg-surface-2/60")} onClick={() => setDisc(String(Math.round(x * 100)))}>
              <TD className="font-medium">-{Math.round(x * 100)}%</TD>
              <TD align="right" className="font-medium">{signedPct(lift(x, row.mean), lang)}</TD>
              <TD align="right" className="whitespace-nowrap text-ink-2">{signedPct(lift(x, row.hdi_low), lang)} – {signedPct(lift(x, row.hdi_high), lang)}</TD>
              <TD align="right" className="text-ink-3">{signedPct(lift(x, row.naive_elasticity), lang)}</TD>
            </TR>
          ))}
        </tbody>
      </Table>
      <p className="text-[12px] text-ink-3">
        Lift = (1 − discount)^(−elasticity) − 1, using the family posterior mean and HDI bounds. Before stock limits: you cannot sell more than is on the shelf.
      </p>
    </div>
  );
}

export default function ElasticityPage() {
  const { t, lang } = useI18n();
  const { data, isLoading, error } = useElasticity();
  const { data: meta } = useMeta();

  const family: FamilyElasticity[] = useMemo(() => data?.family ?? [], [data]);
  const skus: SkuElasticity[] = useMemo(() => data?.sku ?? [], [data]);
  const tested = useMemo(() => skus.filter((s) => s.source === "posterior"), [skus]);

  const stats = useMemo(() => {
    const naive = family.filter((r) => r.naive_elasticity != null);
    const widths = tested.map((s) => s.hdi_high - s.hdi_low).sort((a, b) => a - b);
    return {
      naiveAvg: mean(naive.map((r) => r.naive_elasticity!)),
      postAvg: mean(family.map((r) => r.mean)),
      medianWidth: widths.length ? widths[Math.floor(widths.length / 2)] : NaN,
      untested: skus.length - tested.length,
    };
  }, [family, tested, skus]);

  if (isLoading) return <Loading rows={6} />;
  if (error) return <ErrorState error={error} />;
  if (!family.length) return <Empty>No elasticity model available</Empty>;

  const m = data.meta ?? {};
  const diag = m.diagnostics ?? {};
  const coef = m.coefficients ?? {};
  const storeNames: string[] = (m.stores ?? []).map((id: number) => meta?.stores.find((s) => s.store_id === id)?.store_name ?? `#${id}`);
  const storeList = storeNames.length ? storeNames.join(", ") : "–";
  const sibEffect = coef.b_sibling_promo != null ? Math.exp(coef.b_sibling_promo) - 1 : null;
  const f2 = (v: number | null | undefined) => (v == null || Number.isNaN(v) ? "–" : num(v, lang, 2));
  const byMean = [...family].sort((a, b) => b.mean - a.mean);

  return (
    <div className="space-y-6">
      <PageHeader title={t("el.title")} subtitle={t("el.subtitle")}
        eyebrow={m.version ? `${m.version} · trained until ${dateLabel(m.trained_until, lang, { day: "numeric", month: "short", year: "numeric" })}` : undefined} />

      <Card>
        <CardHeader title={"Why not learn from past markdowns?"}
          subtitle={"The markdown history is biased, so price response is learned from a small randomized test instead."} />
        <CardBody>
          <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
            <Step n={1} icon={<Clock className="h-4 w-4" />} title={"History is confounded"}>
              <p>Every past markdown was applied the day before expiry, on stock left over because demand was weak. A regression on that history credits or blames the discount for demand that was already low, so it badly understates how shoppers respond to price.</p>
              {!Number.isNaN(stats.naiveAvg) && (
                <p className="text-[12.5px] text-ink-3">{`Average naive elasticity: ${f2(stats.naiveAvg)} vs ${f2(stats.postAvg)} from the test.`}</p>
              )}
            </Step>
            <ArrowRight className="hidden h-4 w-4 shrink-0 self-center text-ink-3 lg:block" />
            <Step n={2} icon={<Shuffle className="h-4 w-4" />} title={"A small randomized test"}>
              <p>{`In ${storeNames.length} stores (${storeList}) discounts were assigned at random, independently of stock and demand. That gives clean price variation.`}</p>
              <p className="text-[12.5px] text-ink-3">{num(m.rows, lang)} store-SKU-days · {num(m.skus_tested, lang)} SKUs</p>
            </Step>
            <ArrowRight className="hidden h-4 w-4 shrink-0 self-center text-ink-3 lg:block" />
            <Step n={3} icon={<Network className="h-4 w-4" />} title={"A hierarchical Bayesian model"}>
              <p>Each SKU borrows strength from its family and each family from the chain, so thinly observed products still get a sensible estimate. Test days that sold out are treated as censored demand (demand ≥ sales), not as low demand.</p>
              <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
                <Badge variant="outline">SKU</Badge><ArrowRight className="h-3 w-3 text-ink-3" />
                <Badge variant="outline">Family</Badge><ArrowRight className="h-3 w-3 text-ink-3" />
                <Badge variant="outline">Chain μ = {f2(coef.mu_e)}</Badge>
              </div>
            </Step>
          </div>
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <Card className="xl:col-span-7">
          <CardHeader title={"Price response by family"}
            subtitle={"Dot = estimate from the price test, whisker = 94% HDI. Diamonds: the naive estimate from markdown history, pulled towards zero because past markdowns targeted weak demand."} />
          <CardBody><FamilyIntervalChart rows={family} /></CardBody>
        </Card>
        <Card className="xl:col-span-5">
          <CardHeader title={"Discount → expected demand lift"}
            subtitle={"What a sticker buys in volume, with its uncertainty."} />
          <CardBody><LiftCalculator families={family} /></CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={"Family estimates"}
          subtitle={"An elasticity of 1.5 means a 10% price cut lifts demand by about 17%."} />
        <CardBody className="px-2">
          <Table>
            <THead>
              <TR>
                <TH>Family</TH>
                <TH align="right">Bayesian (mean)</TH>
                <TH align="right">94% HDI</TH>
                <TH align="right">SD</TH>
                <TH align="right">Naive (history)</TH>
                <TH align="right">Markdown days (history)</TH>
                <TH align="right">Test rows</TH>
                <TH align="right">Test SKUs</TH>
              </TR>
            </THead>
            <tbody>
              {byMean.map((r) => (
                <TR key={r.family}>
                  <TD className="whitespace-nowrap font-medium">{r.family}</TD>
                  <TD align="right" className="font-medium">{f2(r.mean)}</TD>
                  <TD align="right" className="whitespace-nowrap text-ink-2">{f2(r.hdi_low)} – {f2(r.hdi_high)}</TD>
                  <TD align="right" className="text-ink-3">{f2(r.sd)}</TD>
                  <TD align="right">{f2(r.naive_elasticity)}</TD>
                  <TD align="right" className="text-ink-2">{r.markdown_share == null ? "–" : pct(r.markdown_share, lang)}</TD>
                  <TD align="right">{num(r.test_rows, lang)}</TD>
                  <TD align="right">{num(r.test_skus, lang)}</TD>
                </TR>
              ))}
            </tbody>
          </Table>
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title={"How precise are the SKU estimates?"}
            subtitle={tested.length
              ? (`${num(tested.length, lang)} SKUs measured in the price test; median width of the 94% interval ${f2(stats.medianWidth)}.`)
              : undefined} />
          <CardBody>
            {tested.length === 0 ? <Empty>No SKU was measured in the price test</Empty> : <SkuPrecisionScatter rows={tested} />}
            <p className="mt-2 text-[12px] text-ink-3">
              {`Narrow intervals are precise enough to act on; wide ones had few discounted days in the test. The ${stats.untested} SKUs outside the test borrow their family's distribution (not shown).`}
            </p>
          </CardBody>
        </Card>
        <Card className="xl:col-span-2">
          <CardHeader title={"Model diagnostics"} subtitle={"Did the sampler converge, and on what data?"} />
          <CardBody className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <DiagTile label={"Divergences"} value={num(diag.divergences ?? 0, lang)}
              status={{ ok: (diag.divergences ?? 0) === 0, label: (diag.divergences ?? 0) === 0 ? "Healthy" : "Check" }}
              note={"Flag hard posterior geometry; 0 means it was explored cleanly."} />
            {diag.rhat_max != null && (
              <DiagTile label="R-hat max" value={num(diag.rhat_max, lang, 3)}
                status={{ ok: diag.rhat_max <= 1.01, label: diag.rhat_max <= 1.01 ? "Converged" : "Check" }}
                note={"Agreement between chains; ≤ 1.01 expected."} />
            )}
            {diag.ess_bulk_min != null && (
              <DiagTile label={"ESS min (bulk)"} value={num(diag.ess_bulk_min, lang)}
                status={{ ok: diag.ess_bulk_min >= 400, label: diag.ess_bulk_min >= 400 ? "Sufficient" : "Low" }}
                note={"Effective independent draws; ≥ 400 recommended."} />
            )}
            <DiagTile label={"Sampling time"} value={m.sampling_seconds != null ? `${num(m.sampling_seconds / 60, lang, 1)} min` : "–"}
              note={"NUTS (nutpie), all chains."} />
            <DiagTile label={"Test rows"} value={num(m.rows, lang)}
              note={`Store-SKU-days across ${storeNames.length} stores, ${num(m.skus_tested, lang)} SKUs.`} />
            <DiagTile label={"Censored share"} value={pct(m.censored_share, lang, 1)}
              note={"Test days that sold out: censored likelihood (demand ≥ sales)."} />
            <DiagTile label={"Cannibalisation (b_sibling_promo)"} value={coef.b_sibling_promo == null ? "–" : num(coef.b_sibling_promo, lang, 3)}
              note={sibEffect != null ? (`When all similar products are on promotion, demand changes by ${pct(sibEffect, lang, 1, true)}.`) : "–"} />
            <DiagTile label={"Hierarchy"} value={<span>μ {f2(coef.mu_e)}</span>}
              note={`Spread between families τ = ${f2(coef.tau)}, between SKUs within a family σ = ${f2(coef.sigma_sku)}.`} />
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
