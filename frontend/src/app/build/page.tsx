"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { BLANK_SPEC, RuleEditor } from "@/components/RuleEditor";
import { Badge, Button, Card, ErrorBox, Skeleton } from "@/components/ui";
import { api, type CatalogItem, type Described, type MarketScan, type RunRequest, type StrategySpec, type Vocabulary } from "@/lib/api";
import { faDigits, faNum, faPct, signClass } from "@/lib/fa";
import { useAppState } from "@/lib/store";

const EXAMPLES = [
  "هر وقت ارزی زیر ۳۰ دقیقه بیشتر از ۱۰ درصد قیمتش جابجا شد در جهت مخالفش وارد ترید شو و تارگتت ۱ درصد باشه",
  "وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش",
  "اگر RSI اتریوم زیر ۳۰ رفت با ۲۰٪ سرمایه بخر، حد ضرر ۴٪ و ۶٪ سود",
];

export default function BuildPage() {
  const router = useRouter();
  const [app, setApp] = useAppState();
  const [text, setText] = useState(app.draftText);
  const [spec, setSpec] = useState<StrategySpec>(app.spec ?? { ...BLANK_SPEC, symbol: app.symbol });
  const [vocab, setVocab] = useState<Vocabulary | null>(null);
  const [described, setDescribed] = useState<Described | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [scan, setScan] = useState<MarketScan | null>(null);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.vocabulary().then(setVocab).catch((e: Error) => setError(e.message));
    api.strategies().then(setCatalog).catch(() => undefined);
  }, []);

  // Every edit is re-validated by the backend, which says in Persian exactly what the bot will do.
  useEffect(() => {
    const t = setTimeout(() => {
      api.describe(spec).then(setDescribed).catch((e: Error) => setError(e.message));
    }, 250);
    return () => clearTimeout(t);
  }, [spec]);

  function edit(next: StrategySpec, keepNotes = false) {
    setSpec(next);
    setApp({ spec: next, symbol: next.symbol });
    setScan(null);
    if (!keepNotes) {
      setWarnings([]);
      setSource(null);
    }
  }

  async function parse() {
    setBusy("parse");
    setError(null);
    setApp({ draftText: text });
    try {
      const r = await api.parse(text, spec.symbol);
      if (r.spec) {
        edit(r.spec, true);
        setWarnings(r.warnings_fa);
        setSource(r.source);
      } else {
        setError(r.error_fa);
      }
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

  async function scanMarkets(valid: StrategySpec) {
    setBusy("scan");
    setError(null);
    try {
      setScan(await api.backtestMarkets({ strategy: "rules", spec: valid, period: "30d" }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const valid = described?.spec ?? null;

  return (
    <>
      <Card title="از کجا شروع کنیم؟">
        <p className="mb-2 text-[13px] leading-6 text-muted">یک الگوی آماده بردارید، یا ایده‌تان را به فارسی بنویسید؛ هر دو در سازندهٔ پایین باز می‌شوند و قابل تغییرند.</p>
        <div className="grid gap-2 sm:grid-cols-2">
          {vocab?.templates.map((t) => (
            <button
              key={t.key}
              onClick={() => edit({ ...BLANK_SPEC, ...t.spec, symbol: spec.symbol } as StrategySpec)}
              className="rounded-xl border border-border bg-surface-2 p-3 text-start hover:border-primary"
            >
              <div className="flex items-center justify-between gap-2 text-sm font-bold">
                {t.title_fa}
                {!t.validated && <Badge tone="accent">آزمایشی</Badge>}
              </div>
              <div className="mt-1 text-xs leading-5 text-muted">{t.note_fa}</div>
            </button>
          )) ?? <Skeleton className="h-20 sm:col-span-2" />}
        </div>

        <label htmlFor="idea" className="mt-4 block text-sm font-bold">
          یا به فارسی بنویسید
        </label>
        <textarea
          id="idea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          maxLength={500}
          className="mt-1.5 w-full resize-none rounded-xl border border-border bg-surface-2 p-3 text-[15px] leading-7 outline-none focus:border-primary"
          placeholder="مثلاً: وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش"
        />
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button key={ex} onClick={() => setText(ex)} className="rounded-full bg-surface-2 px-3 py-1 text-xs text-muted hover:bg-primary-soft hover:text-primary">
              {ex.length > 34 ? ex.slice(0, 34) + "…" : ex}
            </button>
          ))}
        </div>
        <Button variant="secondary" className="mt-3 w-full" onClick={parse} loading={busy === "parse"} disabled={text.trim().length < 3}>
          تبدیل متن به قوانین
        </Button>
        <p className="mt-2 text-[11.5px] leading-5 text-muted">
          هوش مصنوعی فقط متن شما را به قوانین تبدیل می‌کند؛ خودش هیچ سفارشی ثبت نمی‌کند.
        </p>
      </Card>

      <ErrorBox message={error} />

      <Card title="سازندهٔ استراتژی" action={source && <Badge tone="primary">{source === "rules" ? "از متن: تحلیل‌گر قانون‌محور" : "از متن: هوش مصنوعی"}</Badge>}>
        {vocab ? <RuleEditor spec={spec} vocab={vocab} onChange={(s) => edit(s)} /> : <Skeleton className="h-64" />}
      </Card>

      <Card title="ربات دقیقاً این کار را می‌کند">
        {described?.error_fa && <p className="rounded-xl bg-danger/10 p-3 text-[13px] leading-6 text-danger">{described.error_fa}</p>}
        {valid && (
          <ul className="space-y-2">
            {described?.description_fa.map((line) => (
              <li key={line} className="flex gap-2 text-[14.5px] leading-7">
                <span className="mt-2.5 size-1.5 shrink-0 rounded-full bg-primary" aria-hidden />
                {line}
              </li>
            ))}
          </ul>
        )}
        {warnings.length > 0 && (
          <div className="mt-3 space-y-1 rounded-xl bg-accent/10 p-3 text-[13px] leading-6">
            {warnings.map((w) => (
              <p key={w}>⚠️ {w}</p>
            ))}
          </div>
        )}
        {valid && !valid.stop_loss_pct && <p className="mt-3 rounded-xl bg-accent/10 p-3 text-[13px]">⚠️ این استراتژی حد ضرر ندارد.</p>}
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-muted">قوانین ساختاریافته (JSON)</summary>
          <pre dir="ltr" className="mt-2 overflow-x-auto rounded-lg bg-surface-2 p-2 text-[11px] leading-5">
            {JSON.stringify(valid ?? spec, null, 2)}
          </pre>
        </details>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <Button loading={busy === "spec"} disabled={!valid} onClick={() => valid && backtest({ strategy: "rules", spec: valid }, "spec")}>
            بک‌تست روی {valid?.symbol ?? "این بازار"}
          </Button>
          <Button variant="secondary" loading={busy === "scan"} disabled={!valid} onClick={() => valid && scanMarkets(valid)}>
            بک‌تست روی همهٔ بازارهای تومانی
          </Button>
        </div>
        <p className="mt-2 text-[11.5px] text-muted">نتیجهٔ گذشته تضمین آینده نیست. این ابزار توصیهٔ مالی نیست.</p>
      </Card>

      {scan && (
        <Card title="همین قوانین روی همهٔ بازارها (۳۰ روز اخیر)">
          <p className="mb-3 text-[13.5px] leading-6">{scan.headline_fa}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead className="text-muted">
                <tr className="border-b border-border text-start">
                  <th className="py-1.5 text-start font-normal">بازار</th>
                  <th className="font-normal">بازده</th>
                  <th className="font-normal">نگه‌داشتن</th>
                  <th className="font-normal">معامله</th>
                  <th className="font-normal">برد</th>
                  <th className="font-normal">بیشترین افت</th>
                </tr>
              </thead>
              <tbody className="num">
                {scan.rows.map((r) => (
                  <tr key={r.symbol} className="border-b border-border/60 text-center">
                    <td className="py-1.5 text-start">
                      <button className="text-primary hover:underline" onClick={() => edit({ ...(valid ?? spec), symbol: r.symbol })}>
                        {r.name_fa}
                      </button>
                    </td>
                    <td className={signClass(r.return_pct)}>{faPct(r.return_pct, 2, true)}</td>
                    <td className={signClass(r.buy_hold_return_pct)}>{faPct(r.buy_hold_return_pct, 1, true)}</td>
                    <td>{faNum(r.trades, 0)}</td>
                    <td>{r.trades ? faPct(r.win_rate_pct, 0) : "—"}</td>
                    <td>{faPct(r.max_drawdown_pct, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11.5px] text-muted">روی نام بازار بزنید تا سازنده روی همان بازار برود.</p>
        </Card>
      )}

      <Card title="یا یکی از استراتژی‌های کلاسیک">
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
                onClick={() => backtest({ strategy: c.key, symbol: spec.symbol, resolution: "1h", params: c.params }, c.key)}
              >
                بک‌تست
              </Button>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[11.5px] text-muted">روی بازار انتخاب‌شده ({spec.symbol}) با کندل یک‌ساعته اجرا می‌شود.</p>
      </Card>
    </>
  );
}
