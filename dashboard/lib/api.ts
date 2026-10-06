"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export type ReasonCode = { code: string; level: "info" | "warning" | "success" | "action" | "muted"; params: Record<string, unknown> };
export type Tier = "HIGH" | "MEDIUM" | "LOW";

export interface Recommendation {
  store_id: number; sku_id: number; store_name: string; product_name: string; legacy_action: string; legacy_waste_value: number; family: string; subfamily: string;
  action: "MARKDOWN" | "NO_ACTION"; discount_pct: number; markdown_window_days: number; units_to_label: number;
  regular_price: number; new_price: number; stock_on_hand: number; units_expiring_3d: number;
  forecast_today: number; forecast_week: number; baseline_waste_value: number; expected_waste_value: number;
  waste_avoided_value: number; p_waste_baseline: number; p_stockout: number; order_action: "KEEP" | "REDUCE" | "INCREASE";
  order_reference: number; order_recommended: number; donate_units: number; confidence_tier: Tier; confidence_score: number;
  reason_codes: ReasonCode[]; explored: boolean;
}

interface Meta {
  run_id: string; as_of_date: string; data_start: string; data_end: string; demand_model: string; elasticity_model: string;
  rules_version: number; rules_versions?: number[]; n_series: number; n_markdowns: number; n_order_changes: number; n_paths: number; seconds: number;
  generated_at: string; chain_name: string; families: string[]; warehouse?: "snowflake" | "duckdb";
  stores: { store_id: number; store_name: string; city: string; region: string; store_format: string; skus: number; pilot_group: string }[];
}

/** API error with its HTTP status; 503 means the pipeline has not produced the data yet. */
export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(`${status} ${detail}`);
  }
}

export const isNotReady = (e: unknown) => e instanceof ApiError && e.status === 503;

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch { /* non-JSON error body */ }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

async function send<T>(path: string, method: "POST" | "PUT", body: unknown): Promise<T> {
  const res = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(`${res.status}`), { data });
  return data as T;
}

const q = (params: Record<string, string | number | boolean | undefined | null>) => {
  const s = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") s.set(k, String(v)); });
  const str = s.toString();
  return str ? `?${str}` : "";
};

/* eslint-disable @typescript-eslint/no-explicit-any */
export const useMeta = () => useQuery({ queryKey: ["meta"], queryFn: () => get<Meta>("/api/meta"), staleTime: 60_000 });
export const useOverview = () => useQuery({ queryKey: ["overview"], queryFn: () => get<any>("/api/overview") });
export const useRecommendations = (p: { store_id?: number; family?: string; action?: string; tier?: string; q?: string; only_actions?: boolean; sort?: string }) =>
  useQuery({ queryKey: ["recs", p], queryFn: () => get<{ items: Recommendation[]; total: number }>(`/api/recommendations${q({ ...p, limit: 2000 })}`), placeholderData: (prev) => prev });
export const useItem = (store: number, sku: number) =>
  useQuery({ queryKey: ["item", store, sku], queryFn: () => get<any>(`/api/recommendations/${store}/${sku}`) });
export const useHeatmap = () => useQuery({ queryKey: ["heatmap"], queryFn: () => get<any>("/api/risk/heatmap") });
export const useElasticity = () => useQuery({ queryKey: ["elasticity"], queryFn: () => get<any>("/api/elasticity") });
export const useBacktest = () => useQuery({ queryKey: ["backtest"], queryFn: () => get<any>("/api/validation/backtest"), retry: false });
export const usePilot = () => useQuery({ queryKey: ["pilot"], queryFn: () => get<any>("/api/validation/pilot"), retry: false });
export const useModels = () => useQuery({ queryKey: ["models"], queryFn: () => get<any>("/api/models") });
export const useMonitoring = () => useQuery({ queryKey: ["monitoring"], queryFn: () => get<any>("/api/monitoring") });
export const useDataQuality = () => useQuery({ queryKey: ["dq"], queryFn: () => get<any>("/api/data-quality") });
export const useRules = () => useQuery({ queryKey: ["rules"], queryFn: () => get<any>("/api/rules") });

export function useDecide() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { store_id: number; sku_id: number; decision: "ACCEPTED" | "OVERRIDDEN" | "REJECTED"; applied_action?: string; applied_discount_pct?: number; note?: string }) =>
      send<any>("/api/decisions", "POST", b),
    onSuccess: (_d, v) => { qc.invalidateQueries({ queryKey: ["decisions"] }); qc.invalidateQueries({ queryKey: ["item", v.store_id, v.sku_id] }); },
  });
}

export function useWhatIf() {
  return useMutation({ mutationFn: (b: { store_id: number; sku_id: number; discount_pct: number; window_days: number }) => send<any>("/api/simulate", "POST", b) });
}

export function useSaveRules() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { rules: any; comment: string }) => send<any>("/api/rules", "PUT", b),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  });
}

export function useValidateRules() {
  return useMutation({ mutationFn: (b: { rules: any }) => send<any>("/api/rules/validate", "POST", { ...b, comment: "" }) });
}

export function useRecompute() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (store_id: number) => send<any>("/api/recommendations/recompute", "POST", { store_id }),
    onSuccess: () => { ["recs", "overview", "heatmap", "item"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); },
  });
}
