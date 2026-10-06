"use client";

import type { ReactNode } from "react";
import { Boxes, CalendarClock, CircleCheck, CloudSun, ExternalLink, Globe, Layers, Sigma, Target } from "lucide-react";
import { useMeta, useModels } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { dateLabel, num, pct, type Lang } from "@/lib/format";
import { onThisHost } from "@/lib/utils";
import { PageHeader } from "@/components/ui/page";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { InfoTip } from "@/components/ui/tooltip";
import { NotReady, StatusBadge, featureLabel, is503, pts } from "@/components/domain/validation-shared";
import { ImportanceChart, WeatherAblation } from "@/components/domain/models-charts";

/* eslint-disable @typescript-eslint/no-explicit-any */

function Metric({ label, value, note, hint }: { label: string; value: ReactNode; note?: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2.5">
      <div className="flex items-center gap-1 text-[12px] text-ink-3">{label}{hint && <InfoTip>{hint}</InfoTip>}</div>
      <div className="mt-0.5 text-[19px] font-semibold tracking-tight text-ink">{value}</div>
      {note && <div className="mt-0.5 text-[11.5px] leading-snug text-ink-3">{note}</div>}
    </div>
  );
}

function Point({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand">{icon}</div>
      <div>
        <div className="text-[13.5px] font-medium text-ink">{title}</div>
        <div className="text-[13px] leading-relaxed text-ink-2">{children}</div>
      </div>
    </li>
  );
}

function coverageBadge(v: number | null | undefined, target: number) {
  if (v == null) return null;
  return Math.abs(v - target) <= 0.05
    ? <StatusBadge level="good">Calibrated</StatusBadge>
    : <StatusBadge level="warning">Off target</StatusBadge>;
}

const when = (d: string | number | null | undefined, lang: Lang) =>
  d == null ? "–" : dateLabel(typeof d === "number" ? new Date(d).toISOString() : d, lang, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });

function RegistryTable({ rows, lang }: { rows: any[]; lang: Lang }) {
  if (!rows?.length) return <Empty>No registered version</Empty>;
  return (
    <Table>
      <THead><TR><TH>Version</TH><TH>Created</TH><TH>Alias</TH><TH>Status</TH><TH>Run</TH></TR></THead>
      <tbody>
        {rows.map((r) => (
          <TR key={r.version}>
            <TD className="font-medium tabular">v{r.version}</TD>
            <TD className="whitespace-nowrap text-ink-2 tabular">{when(r.created, lang)}</TD>
            <TD>{r.alias ? <Badge variant="brand" icon={<CircleCheck className="h-3 w-3" />}>{r.alias}</Badge> : <span className="text-ink-3">–</span>}</TD>
            <TD>{r.status === "READY" ? <StatusBadge level="good">Ready</StatusBadge>
              : r.status === "FAILED_REGISTRATION" ? <StatusBadge level="critical">Failed</StatusBadge>
              : <StatusBadge level="neutral">{String(r.status ?? "–").toLowerCase()}</StatusBadge>}</TD>
            <TD className="font-mono text-[12px] text-ink-3" title={r.run_id}>{String(r.run_id ?? "").slice(0, 8)}</TD>
          </TR>
        ))}
      </tbody>
    </Table>
  );
}

function runSummary(kind: "demand" | "elasticity", m: Record<string, number>, lang: Lang) {
  if (kind === "demand")
    return [
      m.cal_wape != null && `WAPE ${pct(m.cal_wape, lang, 1)}`,
      m.cal_coverage_80 != null && `cov. 80% ${pct(m.cal_coverage_80, lang, 1)}`,
      m.cal_coverage_95 != null && `95% ${pct(m.cal_coverage_95, lang, 1)}`,
      m.rounds != null && `${num(m.rounds, lang)} rounds`,
    ].filter(Boolean).join(" · ");
  return [
    m.mean_elasticity != null && `mean elasticity ${num(m.mean_elasticity, lang, 2)}`,
    m.divergences != null && `${num(m.divergences, lang)} divergence${m.divergences === 1 ? "" : "s"}`,
    m.sampling_seconds != null && `${num(m.sampling_seconds, lang)} s`,
  ].filter(Boolean).join(" · ");
}

export default function ModelsPage() {
  const { t, lang } = useI18n();
  const { data, isLoading, error } = useModels();
  const { data: meta } = useMeta();
  if (isLoading) return <Loading rows={6} />;
  if (error && is503(error)) return <NotReady title={t("mod.title")} command="perisentra train">No model has been trained yet.</NotReady>;
  if (error) return <ErrorState error={error} />;

  const dm = data.demand;
  const el = data.elasticity;
  const runs = data.runs ?? {};
  const registry = data.registry ?? {};
  const mlflowOk = Object.keys(runs).length > 0 || Object.keys(registry).length > 0;
  const demandRun = (runs.demand ?? []).find((r: any) => r.run_name === dm?.version) ?? runs.demand?.[0];
  const elChampion = (registry.elasticity ?? []).find((r: any) => r.alias === "champion");
  const elRun = (runs.elasticity ?? []).find((r: any) => r.run_id === elChampion?.run_id) ?? (runs.elasticity ?? []).find((r: any) => r.run_name === el?.version);
  const calWeeks = demandRun?.params?.calibration_weeks ?? 8;
  const m = dm?.metrics ?? {};
  const ablation: any[] = dm?.ablation ?? [];
  const kept = ablation.filter((a) => a.keep_weather).length;
  const calib: any[] = [...(dm?.training_report?.calibration_by_family ?? [])].sort((a, b) => b.units - a.units);
  const third = Math.max(1, Math.floor(calib.length / 3));
  const avgWape = (rows: any[]) => rows.reduce((a, r) => a + r.wape, 0) / rows.length;
  const volumeHelps = calib.length >= 3 && avgWape(calib.slice(0, third)) < avgWape(calib.slice(-third));
  const kMax = Math.max(0, ...(dm?.dispersion ?? []).map((r: any) => r.k));
  const kCapped = (dm?.dispersion ?? []).filter((r: any) => r.k >= kMax - 1e-6).length >= 2; // several families pinned at the upper bound
  const confN = new Map<string, number>((dm?.conformal ?? []).filter((c: any) => c.level === 0.8).map((c: any) => [c.family, c.n]));
  const storeName = (id: number) => meta?.stores?.find((s) => s.store_id === id)?.store_name ?? `#${id}`;
  const diag = el?.diagnostics ?? {};
  const allRuns = [
    ...(runs.demand ?? []).map((r: any) => ({ ...r, kind: "demand" as const })),
    ...(runs.elasticity ?? []).map((r: any) => ({ ...r, kind: "elasticity" as const })),
  ].sort((a, b) => String(b.start_time).localeCompare(String(a.start_time))).slice(0, 10);
  const top = dm?.importance?.[0];

  return (
    <div className="space-y-6">
      <PageHeader title={t("mod.title")}
        subtitle={"What runs in production, how it was validated and where it is registered."}
        actions={data.mlflow_ui && (
          <a href={onThisHost(data.mlflow_ui)} target="_blank" rel="noopener noreferrer"
            className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border-strong bg-surface px-3.5 text-[13px] font-medium text-ink hover:bg-surface-2">
            Open MLflow UI<ExternalLink className="h-3.5 w-3.5" />
          </a>
        )} />

      {dm ? (
        <>
          <Card>
            <CardHeader title={"Demand model"}
              subtitle={"One model forecasts every product in every store, 1 to 7 days ahead, with calibrated uncertainty."}
              actions={<><Badge variant="brand" icon={<CircleCheck className="h-3 w-3" />}>champion</Badge><span className="font-mono text-[12px] text-ink-3">{dm.version}</span></>} />
            <CardBody className="grid grid-cols-1 gap-6 xl:grid-cols-5">
              <ul className="space-y-4 xl:col-span-3">
                <Point icon={<Globe className="h-4 w-4" />} title={"One global model"}>
                  {`A single LightGBM model (Tweedie objective, power ${dm.power ?? "–"}) learns from every store-product pair at once, using ${dm.n_features} features.`}
                </Point>
                <Point icon={<Layers className="h-4 w-4" />} title={"Censored demand is recovered"}>
                  {`On a stock-out day, sales are a floor, not demand. An EM loop replaces the target with E[demand | demand ≥ sales]: ${pct(m.censored_share, lang)} of training days were stock-outs, and their demand target was raised by ${num(m.censored_uplift_pct, lang)}% on average.`}
                </Point>
                <Point icon={<Target className="h-4 w-4" />} title={"Calibrated intervals"}>
                  {`Mondrian split-conformal intervals (one calibration per family) fitted on the last ${calWeeks} weeks; a negative-binomial dispersion and a multi-day common shock feed the Monte Carlo paths.`}
                </Point>
                <Point icon={<CalendarClock className="h-4 w-4" />} title={"Direct multi-horizon"}>
                  Lead time (1 to 7 days) is a model input, so each horizon is forecast directly, without feeding forecasts back in.
                </Point>
                <Point icon={<Boxes className="h-4 w-4" />} title={"Thin history"}>
                  A product listed three weeks ago borrows strength from its family, subfamily and store, so its forecast stays sensible.
                </Point>
              </ul>
              <div className="xl:col-span-2">
                <div className="mb-2 text-[12.5px] font-medium text-ink-2">{`Calibration (last ${calWeeks} weeks, held out before the final refit)`}</div>
                <div className="grid grid-cols-2 gap-2.5">
                  <Metric label="WAPE" value={pct(m.cal_wape, lang, 1)} note={"uncensored days"}
                    hint={"Sum of absolute errors / sum of sales."} />
                  <Metric label={"Bias"} value={pct(m.cal_bias, lang, 1, true)} note={"days with ample stock (unconstrained)"} />
                  <Metric label={"80% coverage"} value={pct(m.cal_coverage_80, lang, 1)}
                    note={<span className="inline-flex flex-wrap items-center gap-1.5">{pts(m.cal_coverage_80 - 0.8, lang)} {coverageBadge(m.cal_coverage_80, 0.8)}</span>} />
                  <Metric label={"95% coverage"} value={pct(m.cal_coverage_95, lang, 1)}
                    note={<span className="inline-flex flex-wrap items-center gap-1.5">{pts(m.cal_coverage_95 - 0.95, lang)} {coverageBadge(m.cal_coverage_95, 0.95)}</span>} />
                  <Metric label={"Stock-out days"} value={pct(m.censored_share, lang, 0)}
                    note={`demand raised by +${num(m.censored_uplift_pct, lang)}%`} />
                  <Metric label={"Model size"} value={num(m.rounds, lang)} note={`trees · ${dm.n_features} features`} />
                </div>
                <div className="mt-2.5 text-[12px] text-ink-3">
                  Trained until {dateLabel(dm.trained_until, lang, { day: "numeric", month: "long", year: "numeric" })}
                  {dm.training_report?.rows ? ` · ${num(dm.training_report.rows, lang)} rows` : ""}
                </div>
              </div>
            </CardBody>
          </Card>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader title={"Feature importance"}
                subtitle={top ? (`Recent demand levels dominate: “${featureLabel(top.feature)}” alone carries ${pct(top.share, lang)} of the gain; calendar, promotions and weather refine.`) : undefined} />
              <CardBody><ImportanceChart rows={dm.importance ?? []} /></CardBody>
            </Card>
            <Card>
              <CardHeader title={"Weather ablation"}
                subtitle={`Weather stays only where it helps: kept for ${kept} of ${ablation.length} families.`} />
              <CardBody>
                <WeatherAblation rows={ablation} />
                <p className="mt-3 flex items-start gap-1.5 text-[12px] leading-relaxed text-ink-3">
                  <CloudSun className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  Gain = relative WAPE reduction when weather features are added, on a validation sample. Below a minimum gain, weather is dropped for that family: it would add noise without improving the forecast.
                </p>
              </CardBody>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader title={"Calibration by family"}
                subtitle={`Over the ${calWeeks} calibration weeks, by descending volume.${volumeHelps ? " High-volume families are the most accurate." : ""}`} />
              <CardBody className="px-2">
                <Table>
                  <THead><TR><TH>Family</TH><TH align="right">Units</TH><TH align="right">WAPE</TH><TH align="right">Bias</TH></TR></THead>
                  <tbody>
                    {calib.map((r) => (
                      <TR key={r.family}>
                        <TD>{r.family}</TD>
                        <TD align="right" className="text-ink-2">{num(r.units, lang)}</TD>
                        <TD align="right" className="font-medium">{pct(r.wape, lang, 1)}</TD>
                        <TD align="right">{pct(r.bias, lang, 1, true)}</TD>
                      </TR>
                    ))}
                  </tbody>
                </Table>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title={"Uncertainty by family"}
                subtitle={"What feeds the stock-at-risk Monte Carlo paths."} />
              <CardBody className="px-2">
                <Table>
                  <THead><TR>
                    <TH>Family</TH>
                    <TH align="right"><span className="inline-flex items-center gap-1">NB dispersion k<InfoTip>Negative binomial: the higher k, the less noisy daily demand (closer to Poisson). “≥”: pinned at the estimation’s upper bound.</InfoTip></span></TH>
                    <TH align="right"><span className="inline-flex items-center gap-1">Path σ<InfoTip>Multi-day common shock: the higher σ, the more a whole week can run above or below the forecast.</InfoTip></span></TH>
                    <TH align="right">Calibration rows</TH>
                  </TR></THead>
                  <tbody>
                    {(dm.dispersion ?? []).map((r: any) => (
                      <TR key={r.family}>
                        <TD>{r.family}</TD>
                        <TD align="right">{kCapped && r.k >= kMax - 1e-6 ? <span className="text-ink-2">≥ {num(kMax, lang)}</span> : num(r.k, lang, 1)}</TD>
                        <TD align="right">{num(r.path_sigma, lang, 3)}</TD>
                        <TD align="right" className="text-ink-2">{confN.has(r.family) ? num(confN.get(r.family), lang) : "–"}</TD>
                      </TR>
                    ))}
                  </tbody>
                </Table>
              </CardBody>
            </Card>
          </div>
        </>
      ) : (
        <NotReady title={"Demand model"} command="perisentra train">
          There is no champion demand model yet.
        </NotReady>
      )}

      {el ? (
        <Card>
          <CardHeader title={"Price elasticity model"}
            subtitle={"How much a markdown lifts demand, learned from the in-store price test."}
            actions={<><Badge variant="brand" icon={<CircleCheck className="h-3 w-3" />}>champion</Badge><span className="font-mono text-[12px] text-ink-3">{el.version}</span></>} />
          <CardBody className="grid grid-cols-1 gap-6 xl:grid-cols-5">
            <div className="space-y-4 xl:col-span-2">
              <ul className="space-y-4">
                <Point icon={<Sigma className="h-4 w-4" />} title={"Hierarchical Bayesian"}>
                  Negative-binomial model in PyMC: each product’s elasticity is pulled towards its family’s, and each family’s towards the chain average. Stock-out days enter as censored observations. Sampled with NUTS via nutpie.
                </Point>
              </ul>
              <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1.5 text-[13px]">
                <dt className="text-ink-3">Average elasticity</dt><dd className="text-right font-medium tabular">{num(el.coefficients?.mu_e, lang, 2)}</dd>
                <dt className="col-span-2 -mt-1 text-[11.5px] text-ink-3">{`1% lower price ≈ ${num(el.coefficients?.mu_e, lang, 1)}% more demand`}</dt>
                <dt className="text-ink-3">Spread across families (τ)</dt><dd className="text-right tabular">{num(el.coefficients?.tau, lang, 2)}</dd>
                <dt className="text-ink-3">Spread across products (σ)</dt><dd className="text-right tabular">{num(el.coefficients?.sigma_sku, lang, 2)}</dd>
                <dt className="text-ink-3">Similar products on promo</dt><dd className="text-right tabular">{num(el.coefficients?.b_sibling_promo, lang, 3)}</dd>
                <dt className="text-ink-3">Stock-out days (censored)</dt><dd className="text-right tabular">{pct(el.censored_share, lang)}</dd>
              </dl>
              <div className="text-[13px]"><span className="text-ink-3">{"Test stores: "}</span><span className="text-ink">{(el.stores ?? []).map(storeName).join(", ")}</span></div>
            </div>
            <div className="xl:col-span-3">
              <div className="mb-2 text-[12.5px] font-medium text-ink-2">Sampling diagnostics</div>
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3">
                <Metric label="Divergences" value={num(diag.divergences, lang)}
                  note={diag.divergences === 0 ? <StatusBadge level="good">None</StatusBadge>
                    : diag.divergences == null || diag.divergences < 0 ? <StatusBadge level="neutral">Not recorded</StatusBadge>
                    : <StatusBadge level="warning">Check</StatusBadge>} />
                <Metric label="R-hat max" value={diag.rhat_max == null ? "–" : num(diag.rhat_max, lang, 3)}
                  hint={"Agreement between chains; < 1.01 expected."}
                  note={diag.rhat_max == null ? <StatusBadge level="neutral">Not recorded</StatusBadge>
                    : diag.rhat_max < 1.01 ? <StatusBadge level="good">Converged</StatusBadge>
                    : diag.rhat_max < 1.05 ? <StatusBadge level="warning">Borderline</StatusBadge>
                    : <StatusBadge level="critical">Not converged</StatusBadge>} />
                <Metric label="ESS min" value={diag.ess_bulk_min == null ? "–" : num(diag.ess_bulk_min, lang)}
                  hint={"Smallest bulk effective sample size; ≥ 400 expected."}
                  note={diag.ess_bulk_min == null ? <StatusBadge level="neutral">Not recorded</StatusBadge>
                    : diag.ess_bulk_min >= 400 ? <StatusBadge level="good">Sufficient</StatusBadge>
                    : diag.ess_bulk_min >= 100 ? <StatusBadge level="warning">Low</StatusBadge>
                    : <StatusBadge level="critical">Too low</StatusBadge>} />
                <Metric label={"Sampling time"} value={`${num((el.sampling_seconds ?? 0) / 60, lang, 1)} min`}
                  note={elRun?.params ? `${elRun.params.chains ?? "–"} chains × ${elRun.params.draws ?? "–"} draws` : undefined} />
                <Metric label={"Rows"} value={num(el.rows, lang)} note={"store-product days in the test"} />
                <Metric label={"Products tested"} value={num(el.skus_tested, lang)} note={"others borrow from their family"} />
              </div>
            </div>
          </CardBody>
        </Card>
      ) : (
        <NotReady title={"Price elasticity model"} command="perisentra train">
          There is no champion elasticity model yet.
        </NotReady>
      )}

      {mlflowOk ? (
        <>
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
            <Card>
              <CardHeader title={"MLflow registry: demand"} subtitle={"The “champion” alias marks the version served in production."} />
              <CardBody className="px-2"><RegistryTable rows={registry.demand ?? []} lang={lang} /></CardBody>
            </Card>
            <Card>
              <CardHeader title={"MLflow registry: elasticity"} subtitle={"A new version becomes champion only once its diagnostics pass."} />
              <CardBody className="px-2"><RegistryTable rows={registry.elasticity ?? []} lang={lang} /></CardBody>
            </Card>
          </div>
          <Card>
            <CardHeader title={"Recent runs"} subtitle={"Every training run is tracked in MLflow with its parameters and metrics."} />
            <CardBody className="px-2">
              {allRuns.length ? (
                <Table>
                  <THead><TR><TH>Run</TH><TH>Model</TH><TH>Started</TH><TH>Key metrics</TH><TH>Status</TH></TR></THead>
                  <tbody>
                    {allRuns.map((r) => (
                      <TR key={r.run_id}>
                        <TD className="font-mono text-[12.5px]">{r.run_name}</TD>
                        <TD className="text-ink-2">{r.kind === "demand" ? "Demand" : "Elasticity"}</TD>
                        <TD className="whitespace-nowrap text-ink-2 tabular">{when(r.start_time, lang)}</TD>
                        <TD className="text-[12.5px] text-ink-2 tabular">{runSummary(r.kind, r.metrics ?? {}, lang)}</TD>
                        <TD>{r.status === "FINISHED" ? <StatusBadge level="good">Finished</StatusBadge>
                          : r.status === "FAILED" || r.status === "KILLED" ? <StatusBadge level="critical">Failed</StatusBadge>
                          : <StatusBadge level="neutral">Running</StatusBadge>}</TD>
                      </TR>
                    ))}
                  </tbody>
                </Table>
              ) : <Empty>No tracked run</Empty>}
            </CardBody>
          </Card>
        </>
      ) : (
        <Card>
          <CardHeader title={"MLflow registry and runs"} />
          <CardBody><Empty>MLflow is not reachable from the API right now.</Empty></CardBody>
        </Card>
      )}
    </div>
  );
}
