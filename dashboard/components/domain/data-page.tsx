"use client";

import { useMemo, type ComponentType, type ReactNode } from "react";
import { Boxes, CircleCheck, CircleDashed, CircleX, CloudSun, FlaskConical, Footprints, Layers, Lightbulb, LoaderCircle, Megaphone, PackageX, ScanBarcode, Truck, Warehouse, Database } from "lucide-react";
import { useDataQuality } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { dateLabel, num, pct, type Lang } from "@/lib/format";
import { PageHeader } from "@/components/ui/page";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { Tip } from "@/components/ui/tooltip";
import { Empty, ErrorState, Loading } from "@/components/ui/states";
import { ArchitectureDiagram } from "@/components/domain/data-architecture";
import { LineageGraph, type LineageEdge, type LineageNode } from "@/components/domain/data-lineage";
import { RankedBars } from "@/components/domain/risk-charts";
import { cn } from "@/lib/utils";

/* eslint-disable @typescript-eslint/no-explicit-any */

interface Coverage { source: string; metric: string; value: number; unit: "rows" | "share" | "days" | "units" | "labels" | string }

const SOURCE_ICON: Record<string, ComponentType<{ className?: string }>> = {
  "POS sales": ScanBarcode, "ERP deliveries": Truck, "ERP products": Boxes, "WMS cycle counts": Warehouse, "Waste log": PackageX,
  "Footfall counters": Footprints, "Promo calendar": Megaphone, "Weather (Open-Meteo)": CloudSun, "Price test": FlaskConical, "Modelling panel": Layers,
};

/** Findings worth calling out, with the reason they matter for the models. */
function whyItMatters(metric: string, value: number, lang: Lang): string | null {
  const m = metric.toLowerCase();
  if (m.includes("duplicate rows")) return "Re-sent till batches would double-count sales and inflate forecasts: removed in staging.";
  if (m.includes("lots with an expiry date")) return `${pct(1 - value, lang)} of lots carry no expiry date: it is estimated from delivery date + shelf life, and confidence is lowered.`;
  if (m.includes("censored days")) return "The shelf ran empty on these days, so sales understate demand. The forecast treats them as censored (EM), not as low demand.";
  if (m.includes("markdown stickers")) return "Markdown days coincide with weak demand: excluded from price learning, which relies on the randomized test.";
  if (m.includes("book variance")) return "Book stock drifts from the shelf; cycle counts re-anchor the stock the risk simulation starts from.";
  if (m.includes("randomized test")) return "The clean price variation the elasticity model learns from.";
  return null;
}

function fmtValue(c: Coverage, lang: Lang) {
  switch (c.unit) {
    case "share": return pct(c.value, lang, 1);
    case "days": return `${num(c.value, lang)} days`;
    case "units": return `${num(c.value, lang, 2)} units`;
    default: return num(c.value, lang);
  }
}

function duration(a?: string, b?: string) {
  if (!a || !b) return "–";
  const s = Math.max(0, Math.round((new Date(b).getTime() - new Date(a).getTime()) / 1000));
  if (Number.isNaN(s)) return "–";
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m} min ${String(s % 60).padStart(2, "0")} s` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`;
}

function RunStatus({ status }: { status: string }) {
  const s = status.toLowerCase();
  if (s === "success" || s === "succeeded" || s === "ok") return <Badge variant="good" icon={<CircleCheck className="h-3 w-3" />}>Success</Badge>;
  if (s === "failed" || s === "error") return <Badge variant="critical" icon={<CircleX className="h-3 w-3" />}>Failed</Badge>;
  if (s === "running" || s === "started") return <Badge variant="warning" icon={<LoaderCircle className="h-3 w-3" />}>Running</Badge>;
  return <Badge variant="neutral" icon={<CircleDashed className="h-3 w-3" />}>{status}</Badge>;
}

function DbtStatus({ status, n }: { status: string; n: number }) {
  const s = status.toLowerCase();
  const v = s === "pass" || s === "success" ? "good" : s === "warn" ? "warning" : s === "error" || s === "fail" ? "critical" : "neutral";
  const Icon = v === "good" ? CircleCheck : v === "critical" ? CircleX : CircleDashed;
  return <Badge variant={v} icon={<Icon className="h-3 w-3" />}>{status} · {n}</Badge>;
}

function MiniStat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5">
      <div className="text-[12px] font-medium text-ink-3">{label}</div>
      <div className="mt-0.5 text-[20px] font-semibold leading-tight tracking-tight text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-[11.5px] text-ink-3">{sub}</div>}
    </div>
  );
}

export function DataPage() {
  const { t, lang } = useI18n();
  const { data, isLoading, error } = useDataQuality();

  const coverage: Coverage[] = useMemo(() => data?.coverage ?? [], [data]);
  const grouped = useMemo(() => {
    const m = new Map<string, Coverage[]>();
    coverage.forEach((c) => m.set(c.source, [...(m.get(c.source) ?? []), c]));
    return [...m.entries()];
  }, [coverage]);
  const nodes: LineageNode[] = useMemo(() => data?.lineage?.nodes ?? [], [data]);
  const edges: LineageEdge[] = useMemo(() => data?.lineage?.edges ?? [], [data]);
  const feeds = useMemo(() => {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const out = new Map<string, string[]>();
    edges.forEach((e) => {
      const s = byId.get(e.source), d = byId.get(e.target);
      if (s?.layer === "source" && d) out.set(s.name, [...(out.get(s.name) ?? []), d.name]);
    });
    return out;
  }, [nodes, edges]);
  const runs = useMemo(() => [...(data?.pipeline_runs ?? [])].sort((a: any, b: any) => String(b.started_at).localeCompare(String(a.started_at))), [data]);

  if (isLoading) return <Loading rows={6} />;
  if (error) return <ErrorState error={error} />;

  const dbt = data.dbt ?? {};
  const layerCount = (l: string) => nodes.filter((n) => n.layer === l).length;
  const ingestion: any[] = data.ingestion ?? [];
  const totalRaw = ingestion.reduce((a, r) => a + (r.rows ?? 0), 0);
  const failed: string[] = dbt.tests_failed ?? [];
  const lastLoad = ingestion.map((r) => r.loaded_at).filter(Boolean).sort().at(-1);

  return (
    <div className="space-y-6">
      <PageHeader title={t("data.title")}
        subtitle={"Where the numbers come from, how they are checked, and when the pipeline last ran."} />

      <Card>
        <CardHeader title={"Architecture"}
          subtitle={"From store systems to this morning's actions: every step is versioned, tested and monitored."} />
        <CardBody>
          <ArchitectureDiagram counts={{ raw: layerCount("source") || ingestion.length, staging: layerCount("staging"), intermediate: layerCount("intermediate"), marts: layerCount("marts"), tests: dbt.tests ?? 0 }} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={"Data discovery"}
          subtitle={"What profiling the sources revealed, and what the pipeline does about it. Key findings are highlighted."} />
        <CardBody>
          {grouped.length === 0 ? <Empty /> : (
            <div className="columns-1 gap-4 md:columns-2 2xl:columns-3">
              {grouped.map(([source, items]) => {
                const Icon = SOURCE_ICON[source] ?? Database;
                return (
                  <div key={source} className="mb-4 break-inside-avoid rounded-lg border border-border bg-surface">
                    <div className="flex items-center gap-2 border-b border-border px-3.5 py-2.5">
                      <Icon className="h-4 w-4 text-ink-3" />
                      <span className="text-[13.5px] font-semibold text-ink">{source}</span>
                    </div>
                    <ul className="divide-y divide-border">
                      {items.map((c) => {
                        const why = whyItMatters(c.metric, c.value, lang);
                        return (
                          <li key={c.metric} className={cn("px-3.5 py-2", why && "bg-brand-soft/40")}>
                            <div className="flex items-baseline justify-between gap-3 text-[13px]">
                              <span className={cn("text-ink-2", why && "font-medium text-ink")}>{c.metric}</span>
                              <span className="shrink-0 font-semibold tabular text-ink">{fmtValue(c, lang)}</span>
                            </div>
                            {why && (
                              <div className="mt-1 flex gap-1.5 text-[12px] leading-snug text-ink-3">
                                <Lightbulb className="mt-px h-3.5 w-3.5 shrink-0 text-brand" />
                                <span>{why}</span>
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          <CardHeader title={"Ingestion (raw schema)"}
            subtitle={`${num(ingestion.length, lang)} tables, ${num(totalRaw, lang)} rows loaded${lastLoad ? ` · last load ${dateLabel(lastLoad, lang, { day: "numeric", month: "short", year: "numeric" })}` : ""}`} />
          <CardBody className="px-2">
            {ingestion.length === 0 ? <Empty /> : (
              <Table>
                <THead><TR><TH>Table</TH><TH align="right">Files</TH><TH align="right">Rows</TH><TH>Feeds</TH><TH>Loaded</TH></TR></THead>
                <tbody>
                  {ingestion.map((r) => {
                    const short = String(r.table).replace(/^raw\./, "");
                    const f = feeds.get(short) ?? [];
                    return (
                      <TR key={r.table}>
                        <TD className="font-mono text-[12px]">{r.table}</TD>
                        <TD align="right">{num(r.files, lang)}</TD>
                        <TD align="right" className={cn(!r.rows && "text-ink-3")}>{r.rows ? num(r.rows, lang) : "empty"}</TD>
                        <TD className="text-[12px] text-ink-3">{f.length ? <span className="font-mono">{f.slice(0, 2).join(", ")}{f.length > 2 ? ` +${f.length - 2}` : ""}</span> : "–"}</TD>
                        <TD className="whitespace-nowrap text-ink-2">{dateLabel(r.loaded_at, lang, { day: "numeric", month: "short" })}</TD>
                      </TR>
                    );
                  })}
                </tbody>
              </Table>
            )}
          </CardBody>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader title={"dbt build"}
            subtitle={failed.length
              ? (`${failed.length} failing test(s): fix before trusting the marts.`)
              : "All tests pass: the marts are consistent."} />
          <CardBody className="space-y-4">
            {!dbt.models ? <Empty>No dbt results yet</Empty> : (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <MiniStat label={"Models"} value={num(dbt.models, lang)} />
                  <MiniStat label={"Tests"} value={num(dbt.tests, lang)} />
                  <MiniStat label={"Failing tests"} value={num(failed.length, lang)}
                    sub={failed.length ? <Badge variant="critical" icon={<CircleX className="h-3 w-3" />}>Needs fixing</Badge> : <Badge variant="good" icon={<CircleCheck className="h-3 w-3" />}>All pass</Badge>} />
                  <MiniStat label={"Elapsed"} value={`${num(dbt.elapsed, lang, 1)} s`}
                    sub={dbt.generated_at ? dateLabel(dbt.generated_at, lang, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : undefined} />
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {Object.entries(dbt.status ?? {}).map(([s, n]) => <DbtStatus key={s} status={s} n={n as number} />)}
                </div>
                {failed.length > 0 && (
                  <ul className="space-y-1 text-[12px]">
                    {failed.map((f) => <li key={f} className="flex items-center gap-1.5 font-mono text-critical-ink"><CircleX className="h-3.5 w-3.5" />{f}</li>)}
                  </ul>
                )}
                {(dbt.slowest_models ?? []).length > 0 && (
                  <div>
                    <div className="mb-1 text-[12.5px] font-medium text-ink-2">Slowest models</div>
                    <RankedBars ariaLabel="Slowest dbt models" rows={(dbt.slowest_models as any[]).map((m) => ({ key: m.model, name: m.model, value: m.seconds }))}
                      format={(v) => `${num(v, lang, 2)} s`} />
                  </div>
                )}
              </>
            )}
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title={"dbt lineage"}
          subtitle={`${nodes.length} nodes, ${edges.length} dependencies. Hover a model to see what it reads and what it feeds.`} />
        <CardBody>
          {nodes.length === 0 ? <Empty>No dbt manifest found</Empty> : <LineageGraph nodes={nodes} edges={edges} height={560} />}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={"Pipeline runs"}
          subtitle={"Newest first. Hover a detail for the full message."} />
        <CardBody className="px-2">
          {runs.length === 0 ? <Empty /> : (
            <Table>
              <THead><TR><TH>Step</TH><TH>Status</TH><TH>Started</TH><TH align="right">Duration</TH><TH>Detail</TH><TH>Run</TH></TR></THead>
              <tbody>
                {runs.map((r: any) => (
                  <TR key={`${r.run_id}-${r.step}-${r.started_at}`}>
                    <TD className="whitespace-nowrap font-medium first-letter:uppercase">{String(r.step).replace(/_/g, " ")}</TD>
                    <TD><RunStatus status={String(r.status ?? "")} /></TD>
                    <TD className="whitespace-nowrap text-ink-2">{dateLabel(r.started_at, lang, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</TD>
                    <TD align="right" className="whitespace-nowrap">{duration(r.started_at, r.finished_at)}</TD>
                    <TD>
                      {r.detail ? (
                        <Tip content={<pre className="max-h-60 overflow-auto whitespace-pre-wrap font-mono text-[11.5px]">{r.detail}</pre>}>
                          <span className="block max-w-[440px] cursor-help truncate font-mono text-[12px] text-ink-3">{String(r.detail).split("\n")[0]}</span>
                        </Tip>
                      ) : <span className="text-ink-3">–</span>}
                    </TD>
                    <TD className="whitespace-nowrap font-mono text-[11.5px] text-ink-3">{r.run_id}</TD>
                  </TR>
                ))}
              </tbody>
            </Table>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
