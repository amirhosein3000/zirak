"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, ErrorBox, Skeleton } from "@/components/ui";
import { api, type Preflight } from "@/lib/api";
import { faNum, faPct } from "@/lib/fa";
import { useAppState } from "@/lib/store";

const PROMISES = [
  ["🤖", "هوش مصنوعی هرگز سفارش ثبت نمی‌کند؛ فقط تحلیل و پیشنهاد می‌دهد. اجرا با یک موتور قطعی با محدودیت‌های سخت است."],
  ["🧱", "هر سفارش سقف مبلغ دارد و هر روز سقف زیان؛ با رسیدن به آن، خرید متوقف و موقعیت بسته می‌شود."],
  ["🎯", "سفارش‌های واقعی همیشه «محدود» با حداکثر لغزش مشخص‌اند و اگر پر نشوند خودکار لغو می‌شوند."],
  ["⏻", "کلید توقف اضطراری با یک لمس همهٔ سفارش‌ها را لغو و ربات را متوقف می‌کند."],
  ["🔒", "زیرک هیچ کدی برای برداشت یا انتقال وجه ندارد؛ کلید API فقط با دسترسی معامله ساخته شود."],
];

export default function SafetyPage() {
  const router = useRouter();
  const [app] = useAppState();
  const [pf, setPf] = useState<Preflight | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(null);
    api.preflight().then(setPf).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const t = setTimeout(load, 0);
    return () => clearTimeout(t);
  }, [load]);

  async function start() {
    if (!app.run || !pf) return;
    setBusy(true);
    setError(null);
    try {
      await api.liveStart({ ...app.run, confirm });
      router.push("/dashboard");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const passed = pf?.checks.filter((c) => c.ok).length ?? 0;

  return (
    <>
      <Card title="🛡️ قول‌های ایمنی زیرک">
        <ul className="space-y-2.5">
          {PROMISES.map(([icon, text]) => (
            <li key={text} className="flex gap-2.5 text-[13px] leading-6">
              <span aria-hidden className="text-lg">
                {icon}
              </span>
              {text}
            </li>
          ))}
        </ul>
      </Card>

      <Card
        title="✈️ پیش‌پرواز معاملهٔ واقعی"
        action={
          pf && <Badge tone={pf.ready ? "up" : "accent"}>{pf.ready ? "آماده" : `${faNum(passed, 0)} از ${faNum(pf.checks.length, 0)}`}</Badge>
        }
      >
        {!pf ? (
          <Skeleton className="h-48" />
        ) : (
          <>
            <ul className="space-y-1.5">
              {pf.checks.map((c, i) => (
                <li
                  key={c.key}
                  className="flex items-start gap-2.5 rounded-xl bg-surface-2 p-2.5 text-[13px] leading-6"
                  style={{ animation: `fadeIn .35s ease ${i * 70}ms both` }}
                >
                  <span className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-xs font-bold text-white ${c.ok ? "bg-up" : c.required ? "bg-danger" : "bg-muted"}`}>
                    {c.ok ? "✓" : "✕"}
                  </span>
                  <span>
                    {c.title_fa}
                    {!c.required && <span className="text-muted"> (اختیاری)</span>}
                    {c.detail_fa && <span className="block text-[11.5px] text-muted">{c.detail_fa}</span>}
                  </span>
                </li>
              ))}
            </ul>
            <Button variant="ghost" className="mt-2 w-full" onClick={load}>
              بررسی دوباره
            </Button>

            {Object.keys(pf.fees).length > 0 && (
              <p className="mt-2 text-[12px] text-muted">
                کارمزد شما:{" "}
                {Object.entries(pf.fees)
                  .map(([s, f]) => `${s}: ${f.taker}`)
                  .join("، ")}
              </p>
            )}

            {!pf.ready && (
              <div className="mt-3 rounded-xl bg-accent/10 p-3 text-[12.5px] leading-6">
                برای فعال کردن معاملهٔ واقعی، این مقادیر را در فایل <code dir="ltr">.env</code> سرور تنظیم کنید و سرور را دوباره اجرا کنید:
                <pre dir="ltr" className="mt-2 overflow-x-auto rounded-lg bg-surface p-2 text-[11px] leading-5">
{`DATA_SOURCE=wallex
WALLEX_API_KEY=...        # trade permission only
LIVE_TRADING=true
MAX_ORDER_TMN=500000      # per-order cap
MAX_ORDER_USDT=5
DAILY_LOSS_LIMIT_PCT=3`}
                </pre>
              </div>
            )}

            {pf.ready && (
              <div className="mt-3 space-y-2 rounded-xl border border-danger/40 p-3">
                <p className="text-[13px] font-bold leading-6">
                  {app.run
                    ? `ربات با آخرین استراتژی بک‌تست‌شدهٔ شما (${app.run.strategy === "rules" ? "استراتژی متنی شما" : app.run.strategy}) روی پول واقعی اجرا می‌شود.`
                    : "اول یک استراتژی بسازید و بک‌تست بگیرید."}
                </p>
                <p className="text-[12px] text-muted">
                  حداکثر لغزش هر سفارش {faPct(Number(pf.max_slippage_bps) / 100, 2)} · لغو خودکار سفارش پرنشده پس از{" "}
                  {faNum(pf.order_ttl_s, 0)} ثانیه
                </p>
                <label htmlFor="confirm" className="block text-[12.5px]">
                  برای تأیید، این جمله را دقیقاً تایپ کنید: <b>«{pf.confirm_phrase}»</b>
                </label>
                <input
                  id="confirm"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  className="w-full rounded-xl border border-border bg-surface-2 p-2.5 text-[14px] outline-none focus:border-danger"
                  autoComplete="off"
                />
                <Button variant="danger" className="w-full" disabled={!app.run || confirm.trim() !== pf.confirm_phrase} loading={busy} onClick={start}>
                  شروع معاملهٔ واقعی
                </Button>
              </div>
            )}
          </>
        )}
        <ErrorBox message={error} />
      </Card>
    </>
  );
}
