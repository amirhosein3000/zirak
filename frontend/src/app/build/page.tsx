"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorBox } from "@/components/ui";
import { api, type CatalogItem, type ParseResult, type RunRequest } from "@/lib/api";
import { faDigits } from "@/lib/fa";
import { useAppState } from "@/lib/store";

const EXAMPLES = [
  "وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش",
  "اگر RSI اتریوم زیر ۳۰ رفت با ۲۰٪ سرمایه بخر، حد ضرر ۴٪ و ۶٪ سود",
  "روی چارت ۴ ساعته اگر بیت‌کوین در ۳ روز ۸٪ افت کرد با ۱۵٪ سرمایه بخر و ۵٪ سود بگیر",
];

export default function BuildPage() {
  const router = useRouter();
  const [app, setApp] = useAppState();
  const [text, setText] = useState(app.draftText);
  const [result, setResult] = useState<ParseResult | null>(null);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.strategies().then(setCatalog).catch(() => undefined);
  }, []);

  async function parse() {
    setBusy("parse");
    setError(null);
    setApp({ draftText: text });
    try {
      const r = await api.parse(text, app.symbol);
      setResult(r);
      if (r.spec) setApp({ spec: r.spec });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function backtest(run: RunRequest, key: string) {
    setBusy(key);
    setError(null);
    try {
      const report = await api.backtest(run);
      setApp({ lastReportId: report.id, run });
      router.push(`/backtest?id=${report.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <>
      <Card title="استراتژی‌تان را به فارسی بنویسید">
        <label htmlFor="idea" className="sr-only">
          ایدهٔ معاملاتی
        </label>
        <textarea
          id="idea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          maxLength={500}
          className="w-full resize-none rounded-xl border border-border bg-surface-2 p-3 text-[15px] leading-7 outline-none focus:border-primary"
          placeholder="مثلاً: وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش"
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => setText(ex)} className="rounded-full bg-surface-2 px-3 py-1 text-xs text-muted hover:bg-primary-soft hover:text-primary">
              {ex.length > 34 ? ex.slice(0, 34) + "…" : ex}
            </button>
          ))}
        </div>
        <Button className="mt-3 w-full" onClick={parse} loading={busy === "parse"} disabled={text.trim().length < 3}>
          تبدیل به قوانین دقیق
        </Button>
        <p className="mt-2 text-[11.5px] leading-5 text-muted">
          هوش مصنوعی فقط متن شما را به قوانین تبدیل می‌کند؛ خودش هیچ سفارشی ثبت نمی‌کند. قوانین را بخوانید و تأیید کنید.
        </p>
      </Card>

      <ErrorBox message={error ?? result?.error_fa ?? null} />

      {result?.spec && (
        <Card title="ربات دقیقاً این کار را می‌کند" action={<Badge tone="primary">{result.source === "rules" ? "تحلیل‌گر قانون‌محور" : "هوش مصنوعی"}</Badge>}>
          <ul className="space-y-2">
            {result.description_fa.map((line) => (
              <li key={line} className="flex gap-2 text-[14.5px] leading-7">
                <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
                {line}
              </li>
            ))}
          </ul>
          {result.warnings_fa.length > 0 && (
            <div className="mt-3 space-y-1 rounded-xl bg-accent/10 p-3 text-[13px] leading-6">
              {result.warnings_fa.map((w) => (
                <p key={w}>⚠️ {w}</p>
              ))}
            </div>
          )}
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-muted">قوانین ساختاریافته (JSON)</summary>
            <pre dir="ltr" className="mt-2 overflow-x-auto rounded-lg bg-surface-2 p-2 text-[11px] leading-5">
              {JSON.stringify(result.spec, null, 2)}
            </pre>
          </details>
          <Button
            className="mt-3 w-full"
            loading={busy === "spec"}
            onClick={() => result.spec && backtest({ strategy: "rules", spec: result.spec }, "spec")}
          >
            تأیید و بک‌تست روی داده‌های گذشته
          </Button>
        </Card>
      )}

      <Card title="یا یکی از استراتژی‌های آماده">
        <div className="space-y-2">
          {catalog.map((c) => (
            <div key={c.key} className="flex items-center justify-between gap-3 rounded-xl bg-surface-2 p-3">
              <div>
                <div className="text-sm font-bold">{c.title_fa}</div>
                <div className="mt-0.5 text-xs leading-5 text-muted">{c.description_fa}</div>
                <div className="num mt-1 text-[11px] text-muted" dir="ltr">
                  {faDigits(Object.entries(c.params).map(([k, v]) => `${k}=${v}`).join("  "))}
                </div>
              </div>
              <Button
                variant="secondary"
                className="shrink-0"
                loading={busy === c.key}
                onClick={() => backtest({ strategy: c.key, symbol: app.symbol, resolution: "1h", params: c.params }, c.key)}
              >
                بک‌تست
              </Button>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[11.5px] text-muted">روی بازار انتخاب‌شده ({app.symbol}) با کندل یک‌ساعته اجرا می‌شود.</p>
      </Card>
    </>
  );
}
