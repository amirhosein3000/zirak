// Persian number / money / time formatting. All timestamps from the API are UTC ISO strings;
// we always show Tehran time.

const nf = (max: number, min = 0) =>
  new Intl.NumberFormat("fa-IR", { maximumFractionDigits: max, minimumFractionDigits: min });

// A signed number inside RTL text renders its sign on the wrong side ("۵٪-"). Wrapping it in an
// LTR isolate (LRI ... PDI) keeps "-۵٪" / "+۵٪" intact wherever it is placed.
const ltr = (text: string) => `\u2066${text}\u2069`;

export function faNum(value: number | string | null | undefined, maxDecimals = 2): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  const text = nf(maxDecimals).format(n);
  return n < 0 ? ltr(text) : text;
}

export function faPct(value: number | string | null | undefined, decimals = 1, signed = false): string {
  if (value === null || value === undefined) return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  const sign = signed && n > 0 ? "+" : "";
  const text = `${sign}${nf(decimals).format(n)}٪`;
  return n < 0 || sign ? ltr(text) : text;
}

export const QUOTE_FA: Record<string, string> = { TMN: "تومان", USDT: "تتر" };

/** Toman without decimals; USDT with 2. */
export function money(value: number | string | null | undefined, quote: string): string {
  if (value === null || value === undefined) return "—";
  const decimals = quote === "TMN" ? 0 : 2;
  return `${faNum(value, decimals)} ${QUOTE_FA[quote] ?? quote}`;
}

export function priceDecimals(quote: string): number {
  return quote === "TMN" ? 0 : 2;
}

export function faDigits(text: string): string {
  return text.replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[Number(d)]);
}

export function tehranTime(iso: string, withDate = true): string {
  const opts: Intl.DateTimeFormatOptions = {
    timeZone: "Asia/Tehran",
    hour: "2-digit",
    minute: "2-digit",
    ...(withDate ? { month: "short", day: "numeric" } : {}),
  };
  return new Intl.DateTimeFormat("fa-IR", opts).format(new Date(iso));
}

export function tehranDate(iso: string): string {
  return new Intl.DateTimeFormat("fa-IR", { timeZone: "Asia/Tehran", year: "numeric", month: "short", day: "numeric" }).format(
    new Date(iso),
  );
}

export function signClass(n: number | string | null | undefined): string {
  const v = typeof n === "string" ? Number(n) : n ?? 0;
  if (v > 0) return "text-up";
  if (v < 0) return "text-down";
  return "text-muted";
}

export const RESOLUTION_FA: Record<string, string> = {
  "1m": "یک‌دقیقه‌ای",
  "5m": "۵ دقیقه‌ای",
  "15m": "۱۵ دقیقه‌ای",
  "1h": "یک‌ساعته",
  "4h": "چهارساعته",
  "1d": "روزانه",
};
