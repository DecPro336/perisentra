"use client";

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useBacktest, usePilot } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { PageHeader } from "@/components/ui/page";
import { Segmented } from "@/components/ui/segmented";
import { ErrorState, Loading } from "@/components/ui/states";
import { NotReady, is503 } from "@/components/domain/validation-shared";
import { BacktestView } from "@/components/domain/validation-backtest";
import { PilotView } from "@/components/domain/validation-pilot";

type Tab = "backtest" | "pilot";

function BacktestTab() {
  const { data, isLoading, error } = useBacktest();
  if (isLoading) return <Loading rows={5} />;
  if (error && is503(error))
    return (
      <NotReady title={"Backtest not available yet"} command="perisentra backtest">
        The rolling-origin backtest has not been run yet. It retrains the model at several past dates and compares its forecasts with the store’s current rule.
      </NotReady>
    );
  if (error) return <ErrorState error={error} />;
  return <BacktestView data={data} />;
}

function PilotTab() {
  const { data, isLoading, error } = usePilot();
  if (isLoading) return <Loading rows={5} />;
  if (error && is503(error))
    return (
      <NotReady title={"Pilot results not available yet"} command="perisentra pilot && perisentra evaluate-pilot">
        The pilot runs the engine in 6 stores while matched control stores keep the current rule, then measures the effect with difference-in-differences. Results will appear here once the evaluation has run.
      </NotReady>
    );
  if (error) return <ErrorState error={error} />;
  return <PilotView data={data} />;
}

function ValidationInner() {
  const { t } = useI18n();
  const sp = useSearchParams();
  const router = useRouter();
  const tab: Tab = sp.get("tab") === "pilot" ? "pilot" : "backtest";
  const setTab = (v: Tab) => router.replace(v === "pilot" ? "/validation?tab=pilot" : "/validation", { scroll: false });

  return (
    <div className="space-y-6">
      <PageHeader title={t("val.title")}
        subtitle={tab === "backtest"
          ? "Does the model forecast better than the store's current rule? Measured on past mornings, never peeking at the future."
          : "Does the engine reduce waste in real stores? Measured against matched control stores."}
        actions={<Segmented<Tab> value={tab} onChange={setTab} options={[{ value: "backtest", label: t("val.backtest") }, { value: "pilot", label: t("val.pilot") }]} />} />
      {tab === "backtest" ? <BacktestTab /> : <PilotTab />}
    </div>
  );
}

export default function ValidationPage() {
  return <Suspense fallback={<Loading rows={5} />}><ValidationInner /></Suspense>;
}
