export type Lang = "en";
const CURRENCY = "USD";

const LOCALES: Record<Lang, string> = { en: "en-US" };
const locale = (lang: Lang) => LOCALES[lang];

export function money(v: number | null | undefined, lang: Lang, digits = 0) {
  if (v == null || Number.isNaN(v)) return "–";
  return new Intl.NumberFormat(locale(lang), { style: "currency", currency: CURRENCY, maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
}

export function moneyCompact(v: number | null | undefined, lang: Lang) {
  if (v == null || Number.isNaN(v)) return "–";
  return new Intl.NumberFormat(locale(lang), { style: "currency", currency: CURRENCY, notation: Math.abs(v) >= 10000 ? "compact" : "standard", maximumFractionDigits: Math.abs(v) >= 10000 ? 1 : 0 }).format(v);
}

export function num(v: number | null | undefined, lang: Lang, digits = 0) {
  if (v == null || Number.isNaN(v)) return "–";
  return new Intl.NumberFormat(locale(lang), { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(v);
}

export function pct(v: number | null | undefined, lang: Lang, digits = 0, signed = false) {
  if (v == null || Number.isNaN(v)) return "–";
  const s = new Intl.NumberFormat(locale(lang), { style: "percent", maximumFractionDigits: digits, minimumFractionDigits: digits, signDisplay: signed ? "exceptZero" : "auto" }).format(v);
  return s;
}

export function dateLabel(d: string | null | undefined, lang: Lang, opts: Intl.DateTimeFormatOptions = { day: "numeric", month: "short" }) {
  if (!d) return "–";
  const dt = new Date(d.length === 10 ? `${d}T00:00:00` : d);
  return new Intl.DateTimeFormat(locale(lang), opts).format(dt);
}

export function longDate(d: string | null | undefined, lang: Lang) {
  return dateLabel(d, lang, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}
