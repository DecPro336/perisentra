"use client";

import type { ReactNode } from "react";
import { ArrowRight, BookCheck, ClipboardCheck, Dices, ExternalLink, Percent } from "lucide-react";
import { useBacktest, useMonitoring } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { dateLabel, num, pct, type Lang } from "@/lib/format";
import { PageHeader } from "@/components/ui/page";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { ErrorState, Loading } from "@/components/ui/states";
import { InfoTip } from "@/components/ui/tooltip";
import { NotReady, StatusBadge, featureLabel, is503 } from "@/components/domain/validation-shared";
import { AccuracyChart, FeedbackLoop, sourceLabel } from "@/components/domain/monitoring-parts";

/* eslint-disable @typescript-eslint/no-explicit-any */

function driftLevel(share: number | null | undefined): "good" | "warning" | "critical" | "neutral" {
  if (share == null) return "neutral";
  return share < 0.2 ? "good" : share < 0.5 ? "warning" : "critical";
}

function driftLabel(share: number | null | undefined) {
  const l = driftLevel(share);
  return { good: "Stable", warning: "Moderate drift", critical: "Significant drift", neutral: "Unknown" }[l];
}

const range = (r: [string, string] | undefined, lang: Lang) =>
  r ? `${dateLabel(r[0], lang, { day: "numeric", month: "short" })} – ${dateLabel(r[1], lang, { day: "numeric", month: "short", year: "numeric" })}` : "–";

function Fact({ label, children, hint }: { label: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border px-3 py-2.5">
      <div className="flex items-center gap-1 text-[12px] text-ink-3">{label}{hint && <InfoTip>{hint}</InfoTip>}</div>
      <div className="mt-1 text-[14px] font-medium text-ink">{children}</div>
    </div>
  );
}

const DECISION_ORDER = ["ACCEPTED", "OVERRIDDEN", "REJECTED", "NOT_APPLIED"] as const;
const DECISION_COLOR: Record<string, string> = { ACCEPTED: "var(--series-1)", OVERRIDDEN: "var(--series-4)", REJECTED: "var(--series-5)", NOT_APPLIED: "var(--muted-series)" };
function decisionLabel(d: string) {
  return ({ ACCEPTED: "Accepted", OVERRIDDEN: "Overridden", REJECTED: "Rejected", NOT_APPLIED: "Not applied" } as Record<string, string>)[d] ?? d;
}

export default function MonitoringPage() {
  const { t, lang } = useI18n();
  const { data, isLoading, error } = useMonitoring();
  const { data: bt } = useBacktest();
  if (isLoading) return <Loading rows={6} />;
  if (error && is503(error)) return <NotReady title={t("mon.title")} command="perisentra monitor">No monitoring data yet.</NotReady>;
  if (error) return <ErrorState error={error} />;

  const drift = data.drift;
  const perf = data.performance && Array.isArray(data.performance.weekly) ? data.performance : null;
  const log = data.log ?? {};
  const cols: any[] = drift?.columns ?? [];
  const nDrifted = cols.filter((c) => c.drifted).length;
  const sortedCols = [...cols].sort((a, b) => Number(b.drifted) - Number(a.drifted) || b.score / (b.threshold || 1) - a.score / (a.threshold || 1));
  const share = drift?.drift_share ?? (cols.length ? nDrifted / cols.length : null);
  const mix: Record<string, number> = log.decision_mix ?? {};
  const mixTotal = Object.values(mix).reduce((a, b) => a + b, 0);
  const compliance: number | null = perf?.compliance ?? (mixTotal ? (mix.ACCEPTED ?? 0) / mixTotal : null);
  const weekly: any[] = perf?.weekly ?? [];
  const lastWeek = [...weekly].sort((a, b) => String(a.week).localeCompare(String(b.week))).at(-1);
  const reference: number | null = bt?.observed_uncensored?.model?.wape ?? null;
  const bySource = Object.entries((log.by_source ?? {}) as Record<string, number>).sort((a, b) => b[1] - a[1]);
  const reportHref = "/api/monitoring/drift-report";

  return (
    <div className="space-y-6">
      <PageHeader title={t("mon.title")}
        subtitle={"Is the model still seeing the world it was trained on, and are its forecasts still accurate?"} />

      <Card>
        <CardHeader title={"Feature drift"}
          subtitle={drift
            ? (`${nDrifted} of ${cols.length} monitored features drifted between the reference and current windows.`)
            : "Compares recent data with the data the model learned from."}
          actions={drift
            ? <a href={reportHref} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-strong bg-surface px-2.5 text-[13px] font-medium text-ink hover:bg-surface-2">
                Full Evidently report<ExternalLink className="h-3.5 w-3.5" />
              </a>
            : undefined} />
        <CardBody className="space-y-4">
          {drift ? (
            <>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-lg border border-border px-3 py-2.5">
                  <div className="text-[12px] text-ink-3">Share of features drifting</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className="text-[22px] font-semibold leading-tight tracking-tight text-ink">{pct(share, lang)}</span>
                    <StatusBadge level={driftLevel(share)}>{driftLabel(share)}</StatusBadge>
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-ink-3">{"stable < 20% · moderate < 50%"}</div>
                </div>
                <Fact label={"Reference window"}>{range(drift.reference, lang)}</Fact>
                <Fact label={"Current window"}>{range(drift.current, lang)}</Fact>
                <Fact label={"Rows compared"} hint={`Model monitored: ${drift.model_version}`}>
                  {num(drift.rows?.reference, lang)} <span className="text-ink-3">vs</span> {num(drift.rows?.current, lang)}
                </Fact>
              </div>
              <Table>
                <THead><TR>
                  <TH>Feature</TH><TH>Method</TH><TH align="right">Score</TH><TH align="right">Threshold</TH>
                  <TH align="right">Reference → current mean</TH><TH>Status</TH>
                </TR></THead>
                <tbody>
                  {sortedCols.map((c) => {
                    const change = c.ref_mean ? c.cur_mean / c.ref_mean - 1 : null;
                    return (
                      <TR key={c.column}>
                        <TD className="min-w-[200px]"><div className="font-medium">{featureLabel(c.column)}</div><div className="font-mono text-[11.5px] text-ink-3">{c.column}</div></TD>
                        <TD className="text-[12.5px] text-ink-2">{c.method}</TD>
                        <TD align="right" className={c.drifted ? "font-medium" : ""}>{num(c.score, lang, 3)}</TD>
                        <TD align="right" className="text-ink-2">{num(c.threshold, lang, 2)}</TD>
                        <TD align="right" className="whitespace-nowrap">
                          <span className="text-ink-2">{num(c.ref_mean, lang, 2)}</span>
                          <ArrowRight className="mx-1 inline h-3 w-3 text-ink-3" />
                          <span>{num(c.cur_mean, lang, 2)}</span>
                          {change != null && Number.isFinite(change) && <span className="ml-1.5 text-[11.5px] text-ink-3">({pct(change, lang, 0, true)})</span>}
                        </TD>
                        <TD>{c.drifted ? <StatusBadge level="warning">Drifted</StatusBadge> : <StatusBadge level="good">Stable</StatusBadge>}</TD>
                      </TR>
                    );
                  })}
                </tbody>
              </Table>
              <p className="text-[12px] text-ink-3">
                Drift is not a failure: it flags that the world is changing (season, weather, promotions). The drift check runs before any champion model is replaced.
              </p>
            </>
          ) : (
            <NotReady compact title="" command="perisentra monitor">
              The drift report has not been produced yet. It compares the last 4 weeks with the 8 weeks before, using Evidently.
            </NotReady>
          )}
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title={"Live forecast accuracy"}
            subtitle={perf && lastWeek
              ? (`Weekly WAPE of logged forecasts against actual sales (uncensored days). Last week: ${pct(lastWeek.wape, lang, 1)}${reference != null ? `, vs ${pct(reference, lang, 1)} in the backtest` : ""}.`)
              : "Weekly WAPE of logged forecasts against actual sales."} />
          <CardBody>
            {perf && weekly.length ? <AccuracyChart weekly={weekly} reference={reference} /> : (
              <NotReady compact title="" command="perisentra monitor">
                Live accuracy appears once logged recommendations can be matched with the sales that actually happened.
              </NotReady>
            )}
          </CardBody>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader title={"Decision log"}
            subtitle={"Every recommendation and decision is logged: the basis for offline evaluation."} />
          <CardBody className="space-y-4">
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              <Stat icon={<BookCheck className="h-4 w-4" />} label={"Recommendations"} value={num(log.recommendations, lang)}
                delta={bySource.length ? bySource.map(([s, n]) => `${sourceLabel(s)} ${num(n, lang)}`).join(" · ") : undefined} />
              <Stat icon={<Dices className="h-4 w-4" />} label={"Exploration decisions"} value={num(log.explored, lang)}
                hint={"Picked at random among equivalent actions, with their propensity logged, so a new policy can be evaluated offline without deploying it."}
                delta={log.recommendations ? `${pct(log.explored / log.recommendations, lang, 1)} of recommendations, propensities logged` : undefined} />
              <Stat icon={<ClipboardCheck className="h-4 w-4" />} label={"Store decisions"} value={num(log.decisions, lang)}
                delta={log.decisions ? undefined : "no decision logged yet"} />
              <Stat icon={<Percent className="h-4 w-4" />} label={"Compliance"} value={compliance == null ? "–" : pct(compliance, lang, 0)}
                delta={"recommendations applied as given"} />
            </div>
            {mixTotal > 0 && (
              <div>
                <div className="mb-1.5 text-[12px] text-ink-3">Decision mix</div>
                <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-2" role="img" aria-label="Decision mix">
                  {DECISION_ORDER.filter((d) => mix[d]).map((d) => (
                    <div key={d} className="h-full border-r-2 border-surface last:border-0" style={{ width: `${(100 * mix[d]) / mixTotal}%`, background: DECISION_COLOR[d] }} />
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-2">
                  {DECISION_ORDER.filter((d) => mix[d]).map((d) => (
                    <span key={d} className="inline-flex items-center gap-1.5 tabular">
                      <span className="h-2 w-2 rounded-sm" style={{ background: DECISION_COLOR[d] }} />{decisionLabel(d)} {num(mix[d], lang)} · {pct(mix[d] / mixTotal, lang)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={"The feedback loop"}
          subtitle={"Every morning produces the data that improves next week's model."} />
        <CardBody className="pb-7">
          <FeedbackLoop stats={[
            `${num(log.recommendations, lang)} logged`,
            `${num(log.decisions, lang)} decisions${compliance != null ? ` · ${pct(compliance, lang)} applied` : ""}`,
            lastWeek ? `WAPE ${pct(lastWeek.wape, lang, 1)} last week` : "awaiting first match",
            drift ? <span key="v">Champion <span className="font-mono text-[11.5px] font-normal text-ink-3">{drift.model_version}</span></span> : "champion checked weekly",
          ]} />
        </CardBody>
      </Card>
    </div>
  );
}
