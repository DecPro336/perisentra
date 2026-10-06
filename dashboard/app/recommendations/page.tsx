"use client";

import Link from "next/link";
import { Suspense, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowDownUp, ChevronRight, Download, Search } from "lucide-react";
import * as Switch from "@radix-ui/react-switch";
import { flexRender, getCoreRowModel, getPaginationRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useMeta, useRecommendations, type Recommendation } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { money, num, pct } from "@/lib/format";
import { PageHeader } from "@/components/ui/page";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Stat } from "@/components/ui/stat";
import { ErrorState, Empty, Loading } from "@/components/ui/states";
import { ActionBadge, ConfidenceBadge, DonateBadge, OrderBadge } from "@/components/domain/badges";
import { ReasonList } from "@/components/domain/reasons";
import { cn } from "@/lib/utils";

function useParamState() {
  const sp = useSearchParams();
  const router = useRouter();
  const get = (k: string) => sp.get(k) ?? "";
  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp.toString());
    if (v) next.set(k, v); else next.delete(k);
    router.replace(`/recommendations?${next.toString()}`, { scroll: false });
  };
  return { get, set };
}

function toCsv(rows: Recommendation[]) {
  const cols: (keyof Recommendation)[] = ["store_id", "sku_id", "product_name", "family", "action", "discount_pct", "markdown_window_days", "units_to_label",
    "regular_price", "new_price", "stock_on_hand", "units_expiring_3d", "forecast_today", "baseline_waste_value", "expected_waste_value",
    "waste_avoided_value", "order_action", "order_reference", "order_recommended", "donate_units", "confidence_tier"];
  const esc = (v: unknown) => { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

function RecommendationsInner() {
  const { t, lang } = useI18n();
  const router = useRouter();
  const { get, set } = useParamState();
  const { data: meta } = useMeta();
  const store = get("store");
  const family = get("family");
  const action = get("action");
  const tier = get("tier");
  const only = get("only") === "1";
  const [q, setQ] = useState(get("q"));
  const { data, isLoading, error, isFetching } = useRecommendations({ store_id: store ? Number(store) : undefined, family: family || undefined, action: action || undefined, tier: tier || undefined, q: q || undefined, only_actions: only });
  const [sorting, setSorting] = useState<SortingState>([]);

  const columns = useMemo<ColumnDef<Recommendation>[]>(() => [
    { id: "product", header: t("rec.col.product"), accessorKey: "product_name", cell: ({ row: { original: r } }) => (
      <div className="min-w-[180px]"><div className="font-medium text-ink">{r.product_name}</div><div className="text-[12px] text-ink-3">{r.family} · {store ? r.subfamily : r.store_name}</div></div>) },
    { id: "action", header: t("rec.col.action"), accessorFn: (r) => (r.action === "MARKDOWN" ? r.discount_pct : -1), cell: ({ row: { original: r } }) => (
      <div className="flex flex-col items-start gap-1">
        <ActionBadge action={r.action} discount={r.discount_pct} window={r.action === "MARKDOWN" ? r.markdown_window_days : undefined} />
        {r.action === "MARKDOWN" && <span className="text-[12px] text-ink-3 tabular">{r.units_to_label} {t("common.units")} · {money(r.regular_price, lang, 2)} → <span className="font-medium text-ink">{money(r.new_price, lang, 2)}</span></span>}
        <DonateBadge units={r.donate_units} />
      </div>) },
    { id: "stock", header: t("rec.col.stock"), accessorKey: "stock_on_hand", meta: { align: "right" }, cell: ({ row: { original: r } }) => (
      <div className="text-right tabular"><div>{num(r.stock_on_hand, lang)}</div><div className={cn("text-[12px]", r.units_expiring_3d ? "text-serious-ink" : "text-ink-3")}>{num(r.units_expiring_3d, lang)} ≤3d</div></div>) },
    { id: "risk", header: t("rec.col.risk"), accessorKey: "baseline_waste_value", meta: { align: "right" }, cell: ({ row: { original: r } }) => (
      <div className="text-right tabular"><div>{money(r.baseline_waste_value, lang)}</div><div className="text-[12px] text-ink-3">{pct(r.p_waste_baseline, lang)}</div></div>) },
    { id: "avoided", header: t("rec.col.avoided"), accessorKey: "waste_avoided_value", meta: { align: "right" }, cell: ({ getValue }) => (
      <div className={cn("text-right tabular", getValue<number>() > 0.005 ? "text-good-ink" : "text-ink-3")}>{money(getValue<number>(), lang)}</div>) },
    { id: "order", header: t("rec.col.order"), accessorKey: "order_recommended", cell: ({ row: { original: r } }) => <OrderBadge action={r.order_action} reference={r.order_reference} recommended={r.order_recommended} /> },
    { id: "confidence", header: t("rec.col.confidence"), accessorKey: "confidence_score", cell: ({ row: { original: r } }) => <ConfidenceBadge tier={r.confidence_tier} short /> },
    { id: "why", header: t("rec.col.why"), enableSorting: false, cell: ({ row: { original: r } }) => <div className="line-clamp-3 min-w-[220px] max-w-[300px]"><ReasonList reasons={r.reason_codes.slice(0, 1)} compact /></div> },
    { id: "go", header: "", enableSorting: false, cell: () => <ChevronRight className="h-4 w-4 text-ink-3" /> },
  ], [t, lang, store]);

  const items = useMemo(() => data?.items ?? [], [data]);
  // TanStack Table returns non-memoisable functions; this app does not use the React Compiler.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({ data: items, columns, state: { sorting }, onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(), getSortedRowModel: getSortedRowModel(), getPaginationRowModel: getPaginationRowModel(), initialState: { pagination: { pageSize: 50 } } });

  const summary = useMemo(() => ({
    atRisk: items.reduce((a, r) => a + r.baseline_waste_value, 0), avoided: items.reduce((a, r) => a + r.waste_avoided_value, 0),
    md: items.filter((r) => r.action === "MARKDOWN").length, orders: items.filter((r) => r.order_action !== "KEEP").length,
    donations: items.filter((r) => r.donate_units > 0).length,
  }), [items]);

  const storeOptions = [{ value: "", label: t("top.allStores") }, ...(meta?.stores ?? []).map((s) => ({ value: String(s.store_id), label: s.store_name }))];
  const familyOptions = [{ value: "", label: t("common.all") }, ...(meta?.families ?? []).map((f) => ({ value: f, label: f }))];
  const actionOptions = [{ value: "", label: t("common.all") }, { value: "MARKDOWN", label: t("action.MARKDOWN") }, { value: "ORDER", label: t("rec.filter.ORDER") },
    { value: "DONATE", label: t("rec.filter.DONATE") }, { value: "STOCKOUT", label: t("rec.filter.STOCKOUT") }, { value: "NO_ACTION", label: t("action.NO_ACTION") }];
  const tierOptions = [{ value: "", label: t("common.all") }, ...(["HIGH", "MEDIUM", "LOW"] as const).map((x) => ({ value: x, label: t(`tier.short.${x}`) }))];

  const download = () => {
    const blob = new Blob([toCsv(items)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `perisentra-actions-${meta?.as_of_date ?? "today"}${store ? `-store${store}` : ""}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="space-y-5">
      <PageHeader title={t("rec.title")} subtitle={t("rec.subtitle")} actions={<Button variant="outline" onClick={download} disabled={!items.length}><Download className="h-4 w-4" />{t("common.export")}</Button>} />

      <div className="flex flex-wrap items-center gap-2">
        <Select label={t("top.store")} value={store} onChange={(v) => set("store", v)} options={storeOptions} className="min-w-[220px]" />
        <Select label={t("rec.filters.family")} value={family} onChange={(v) => set("family", v)} options={familyOptions} />
        <Select label={t("rec.filters.action")} value={action} onChange={(v) => set("action", v)} options={actionOptions} />
        <Select label={t("rec.filters.tier")} value={tier} onChange={(v) => set("tier", v)} options={tierOptions} />
        <label className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-ink-3" />
          <input value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => set("q", q)} placeholder={t("common.search")} aria-label={t("common.search")}
            className="h-9 w-56 rounded-lg border border-border-strong bg-surface pl-8 pr-3 text-[13px] text-ink placeholder:text-ink-3" />
        </label>
        <label className="ml-1 flex cursor-pointer items-center gap-2 text-[13px] text-ink-2">
          <Switch.Root checked={only} onCheckedChange={(c) => set("only", c ? "1" : "")} className="relative h-5 w-9 rounded-full bg-surface-3 data-[state=checked]:bg-brand">
            <Switch.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
          </Switch.Root>
          {t("rec.filters.onlyActions")}
        </label>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Stat label={"Lines"} value={num(data?.total ?? 0, lang)} />
        <Stat label={t("ov.atRisk")} value={money(summary.atRisk, lang)} />
        <Stat label={t("ov.avoided")} value={money(summary.avoided, lang)} deltaTone="good" />
        <Stat label={t("ov.markdowns")} value={num(summary.md, lang)} />
        <Stat label={t("ov.orders")} value={num(summary.orders, lang)} delta={`${num(summary.donations, lang)} ${t("ov.donations").toLowerCase()}`} />
      </div>

      {error ? <ErrorState error={error} /> : isLoading ? <Loading rows={6} /> : (
        <Card className={cn("overflow-hidden transition-opacity", isFetching && "opacity-60")}>
          {items.length === 0 ? <Empty /> : (
            <>
              <div className="scroll-thin overflow-x-auto">
                <table className="w-full border-collapse text-[13px]">
                  <thead className="bg-surface-2/60">
                    {table.getHeaderGroups().map((hg) => (
                      <tr key={hg.id}>
                        {hg.headers.map((h) => {
                          const right = (h.column.columnDef.meta as { align?: string } | undefined)?.align === "right";
                          return (
                            <th key={h.id} className={cn("whitespace-nowrap border-b border-border px-3 py-2.5 text-[12px] font-medium text-ink-3", right ? "text-right" : "text-left")}>
                              {h.column.getCanSort() ? (
                                <button onClick={h.column.getToggleSortingHandler()} className={cn("inline-flex items-center gap-1 hover:text-ink", right && "flex-row-reverse")}>
                                  {flexRender(h.column.columnDef.header, h.getContext())}<ArrowDownUp className="h-3 w-3 opacity-60" />
                                </button>
                              ) : flexRender(h.column.columnDef.header, h.getContext())}
                            </th>
                          );
                        })}
                      </tr>
                    ))}
                  </thead>
                  <tbody>
                    {table.getRowModel().rows.map((row) => (
                      <tr key={row.id} className="cursor-pointer border-b border-border align-top last:border-0 hover:bg-surface-2/70"
                        // the whole row opens the item (the links inside only cover each cell's content)
                        onClick={(e) => { if (!e.defaultPrevented) router.push(`/item/${row.original.store_id}/${row.original.sku_id}`); }}>
                        {row.getVisibleCells().map((cell) => (
                          <td key={cell.id} className="px-3 py-3">
                            <Link prefetch={false} href={`/item/${row.original.store_id}/${row.original.sku_id}`} className="block" tabIndex={cell.column.id === "product" ? 0 : -1}>
                              {flexRender(cell.column.columnDef.cell, cell.getContext())}
                            </Link>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex items-center justify-between border-t border-border px-4 py-2.5 text-[12.5px] text-ink-3">
                <span className="tabular">{num(table.getState().pagination.pageIndex * 50 + 1, lang)}–{num(Math.min((table.getState().pagination.pageIndex + 1) * 50, items.length), lang)} / {num(items.length, lang)}</span>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>←</Button>
                  <Button size="sm" variant="outline" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>→</Button>
                </div>
              </div>
            </>
          )}
        </Card>
      )}
    </div>
  );
}

export default function RecommendationsPage() {
  return <Suspense fallback={<Loading rows={6} />}><RecommendationsInner /></Suspense>;
}
