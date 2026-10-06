"use client";

import type { ReactNode } from "react";
import { Activity, ArrowDown, ArrowRight, BrainCircuit, Database, Download, Layers, LayoutDashboard, RotateCcw, Scale, Server } from "lucide-react";
import { useMeta } from "@/lib/api";
import { cn } from "@/lib/utils";

function Stage({ step, icon, title, sub, children, footer, className }: {
  step: string; icon: ReactNode; title: string; sub?: string; children?: ReactNode; footer?: ReactNode; className?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-1 flex-col rounded-lg border border-border bg-surface-2/50 p-3", className)}>
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-3">{icon}{step}</div>
      <div className="mt-1 text-[13.5px] font-semibold leading-snug text-ink">{title}</div>
      {sub && <div className="text-[12px] leading-snug text-ink-3">{sub}</div>}
      {children && <div className="mt-2 flex flex-1 flex-col gap-1">{children}</div>}
      {footer && <div className="mt-2 border-t border-border pt-2 text-[11.5px] leading-snug text-ink-3">{footer}</div>}
    </div>
  );
}

function Item({ children, mono }: { children: ReactNode; mono?: boolean }) {
  return <div className={cn("rounded-md border border-border bg-surface px-2 py-1 text-[12px] leading-snug text-ink-2", mono && "break-all font-mono text-[11px]")}>{children}</div>;
}

function Arrow() {
  return (
    <div className="flex shrink-0 items-center justify-center text-ink-3" aria-hidden>
      <ArrowRight className="hidden h-4 w-4 xl:block" />
      <ArrowDown className="h-4 w-4 xl:hidden" />
    </div>
  );
}

/** Pipeline architecture drawn in HTML/CSS: sources → ingestion → dbt → models → decisions → serving, with monitoring underneath. */
export function ArchitectureDiagram({ counts }: { counts: { raw: number; staging: number; intermediate: number; marts: number; tests: number } }) {
  const { data: meta } = useMeta();
  const offline = meta?.warehouse === "duckdb";
  const sources = ["POS (till sales)", "ERP: products, deliveries, prices", "WMS: movements, cycle counts", "Waste log", "Promo calendar", "Footfall counters", "Open-Meteo (weather)", "Nager.Date (holidays)"];
  return (
    <div className="space-y-2">
      <div className="flex flex-col gap-2 xl:flex-row xl:items-stretch">
        <Stage step={"Sources"} icon={<Database className="h-3.5 w-3.5" />} title={"Source systems"} className="xl:flex-[1.25]">
          {sources.map((s) => <Item key={s}>{s}</Item>)}
        </Stage>
        <Arrow />
        <Stage step={"Ingestion"} icon={<Download className="h-3.5 w-3.5" />} title={"Raw schema"} className="xl:flex-[1.15]"
          sub={offline ? `${counts.raw} tables, loaded as received` : `${counts.raw} tables, PUT + COPY INTO`}
          footer={"Airflow: daily DAG at 05:00, weekly retraining (Mon 02:00)"}>
          <Item mono>pos_daily_sales</Item>
          <Item mono>erp_deliveries</Item>
          <Item mono>erp_products</Item>
          <Item>… per-file ingestion log</Item>
        </Stage>
        <Arrow />
        <Stage step="dbt" icon={<Layers className="h-3.5 w-3.5" />} title={"Tested transformations"}
          sub={offline ? "Offline DuckDB copy (same models)" : "Snowflake · key-pair service user"}
          footer={`${counts.tests} dbt tests: unique, not null, relationships, ranges`}>
          <Item><b className="font-medium text-ink">staging</b> · {counts.staging} models: typing, de-duplication</Item>
          <Item><b className="font-medium text-ink">intermediate</b> · {counts.intermediate} models: lots, stock-outs, calendars</Item>
          <Item><b className="font-medium text-ink">marts</b> · {counts.marts} models: facts & dimensions</Item>
        </Stage>
        <Arrow />
        <Stage step={"Models"} icon={<BrainCircuit className="h-3.5 w-3.5" />} title={"Forecast & quantify"}
          footer={"Tracked and versioned in MLflow (champion / challenger)"}>
          <Item>Demand: LightGBM + censored EM + conformal intervals</Item>
          <Item>Elasticity: hierarchical PyMC</Item>
          <Item>Risk: Monte Carlo over shelf lots</Item>
        </Stage>
        <Arrow />
        <Stage step={"Decision"} icon={<Scale className="h-3.5 w-3.5" />} title={"Decision engine"}>
          <Item>Versioned business rules</Item>
          <Item>Markdown, order, donation</Item>
          <Item>Reason codes & confidence</Item>
        </Stage>
        <Arrow />
        <Stage step={"Serving"} icon={<Server className="h-3.5 w-3.5" />} title="FastAPI">
          <Item>REST API + what-if</Item>
          <div className="flex items-center justify-center py-0.5 text-ink-3"><ArrowDown className="h-3.5 w-3.5" /></div>
          <Item><span className="inline-flex items-center gap-1"><LayoutDashboard className="h-3.5 w-3.5 text-ink-3" />This dashboard</span></Item>
        </Stage>
      </div>
      <div className="flex flex-col gap-2 rounded-lg border border-dashed border-border-strong px-3 py-2.5 text-[12.5px] text-ink-2 sm:flex-row sm:items-center">
        <span className="inline-flex items-center gap-1.5 font-semibold text-ink"><Activity className="h-4 w-4 text-ink-3" />Monitoring</span>
        <span className="text-ink-3">
          Evidently (data and forecast drift), accuracy by store, recommendation log and store decisions
        </span>
        <span className="inline-flex items-center gap-1.5 text-ink-3 sm:ml-auto"><RotateCcw className="h-3.5 w-3.5" />feeds retraining</span>
      </div>
    </div>
  );
}
