"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { LineChart } from "@/components/LineChart";
import { TradeLog } from "@/components/TradeLog";
import { Badge, Button, Card, Empty, ErrorBox, Skeleton, Stat } from "@/components/ui";
import { api, type BotStatus } from "@/lib/api";
import { RESOLUTION_FA, faNum, faPct, money, signClass, tehranTime } from "@/lib/fa";
import { useAppState } from "@/lib/store";

const HALT_FA: Record<string, string> = {
  daily_loss_limit: "سقف زیان روزانه",
  kill_switch: "کلید توقف اضطراری",
  api: "کلید توقف اضطراری",
};

export default function DashboardPage() {
  const [app] = useAppState();
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.botStatus());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const t = setInterval(refresh, 1500);
    return () => {
      clearTimeout(first);
      clearInterval(t);
    };
  }, [refresh]);

  async function act(key: string, fn: () => Promise<unknown>, done?: string) {
    setBusy(key);
    setNotice(null);
    try {
      await fn();
      if (done) setNotice(done);
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const bot = status?.bot;
  const quote = bot?.symbol.endsWith("USDT") ? "USDT" : "TMN";
  const dec = quote === "TMN" ? 0 : 2;

  return (
    <>
      {/* The kill switch is always visible and needs one tap. */}
      <Button
        variant="danger"
        className="min-h-14 w-full text-base"
        loading={busy === "kill"}
        disabled={status?.kill_engaged && !status?.running}
        onClick={() => act("kill", () => api.kill(), "کلید توقف فعال شد: همهٔ سفارش‌های باز لغو و ربات متوقف شد.")}
      >
        ⏻ کلید توقف اضطراری
      </Button>
      {status?.mode === "live" && status.running && (
        <div className="animate-pulse rounded-xl bg-danger p-3 text-center text-sm font-bold text-white">
          ⚠️ معاملهٔ واقعی با پول واقعی در جریان است
        </div>
      )}
      {notice && <div className="rounded-xl bg-primary-soft p-3 text-sm text-primary">{notice}</div>}
      <ErrorBox message={error ?? status?.error ?? null} />

      {!status ? (
        <Skeleton className="h-40" />
      ) : !bot ? (
        <Empty>
          هنوز رباتی اجرا نشده است. اول <Link href="/build" className="font-bold text-primary">استراتژی بسازید</Link> و بعد از بک‌تست، آن را در حالت کاغذی اجرا کنید.
        </Empty>
      ) : (
        <>
          <Card
            title={bot.strategy.title_fa || bot.strategy.key}
            action={
              status.running ? (
                <Badge tone="up">● در حال اجرا</Badge>
              ) : bot.killed ? (
                <Badge tone="danger">متوقف (کلید اضطراری)</Badge>
              ) : (
                <Badge>متوقف</Badge>
              )
            }
          >
            <p className="text-xs text-muted">
              {bot.symbol} · کندل {RESOLUTION_FA[bot.resolution] ?? bot.resolution} ·{" "}
              {status.mode === "live" ? (
                <b className="text-danger">معاملهٔ واقعی روی والکس · {faNum(status.progress.done, 0)} کندل جدید</b>
              ) : status.mode === "paper-live" ? (
                <>حالت کاغذی روی دادهٔ زندهٔ والکس · {faNum(status.progress.done, 0)} کندل جدید</>
              ) : (
                <>حالت کاغذی روی دادهٔ بازپخش · {faNum(status.progress.done, 0)} از {faNum(status.progress.total, 0)} کندل</>
              )}
            </p>
            {bot.halted && !bot.killed && (
              <p className="mt-2 rounded-lg bg-accent/10 p-2 text-[13px]">مدیر ریسک خرید جدید را متوقف کرده است: {HALT_FA[bot.halt_reason] ?? bot.halt_reason}</p>
            )}
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Stat label="ارزش کل" value={money(bot.equity, quote)} />
              <Stat label="سود / زیان" value={faPct(bot.pnl_pct, 2, true)} valueClass={signClass(bot.pnl)} hint={money(bot.pnl, quote)} />
              <Stat label="سود محقق‌شده" value={money(bot.realized_pnl, quote)} valueClass={signClass(bot.realized_pnl)} />
              <Stat label="سود باز" value={money(bot.unrealized_pnl, quote)} valueClass={signClass(bot.unrealized_pnl)} />
              <Stat label="موقعیت" value={faNum(bot.position_qty, 6)} hint={bot.avg_entry ? `میانگین خرید ${faNum(bot.avg_entry, dec)}` : "بدون موقعیت"} />
              <Stat label="قیمت فعلی" value={faNum(bot.price, dec)} hint={`نقد آزاد: ${money(bot.quote_free, quote)}`} />
            </div>
            <div className="mt-3 flex gap-2">
              {status.running && (
                <Button variant="secondary" className="flex-1" loading={busy === "stop"} onClick={() => act("stop", () => api.botStop(), "ربات متوقف شد.")}>
                  توقف عادی
                </Button>
              )}
              {status.kill_engaged && !status.running && (
                <Button variant="secondary" className="flex-1" loading={busy === "reset"} onClick={() => act("reset", () => api.killReset(), "کلید توقف غیرفعال شد.")}>
                  غیرفعال کردن کلید توقف
                </Button>
              )}
              {!status.running && !status.kill_engaged && app.run && (
                <Button className="flex-1" loading={busy === "start"} onClick={() => act("start", () => api.botStart({ ...app.run!, speed_s: 0.5 }), "ربات دوباره شروع شد.")}>
                  شروع دوباره
                </Button>
              )}
            </div>
          </Card>

          <ShieldStrip log={status.log} />

          <Card title="قیمت و تصمیم‌های ربات">
            {status.equity_curve.length > 1 ? (
              <LineChart
                ariaLabel="نمودار زندهٔ قیمت با نشانگر تصمیم‌ها"
                x={status.equity_curve.map((p) => p.ts)}
                series={[{ name: "قیمت", color: "var(--chart-1)", values: status.equity_curve.map((p) => p.price) }]}
                format={(v) => faNum(v, dec)}
                markers={status.log
                  .filter((e) => !e.decision.approved || Number(e.filled_qty) > 0)
                  .map((e) => ({ ts: e.ts, side: e.side, label: e.note_fa, blocked: !e.decision.approved }))}
                height={170}
              />
            ) : (
              <Skeleton className="h-40" />
            )}
          </Card>

          <Card title="ارزش سرمایه (زنده)">
            {status.equity_curve.length > 1 ? (
              <LineChart
                ariaLabel="نمودار زندهٔ ارزش سرمایه"
                x={status.equity_curve.map((p) => p.ts)}
                series={[{ name: "ارزش کل", color: "var(--chart-1)", values: status.equity_curve.map((p) => p.equity) }]}
                format={(v) => faNum(v, dec)}
                height={170}
              />
            ) : (
              <Skeleton className="h-40" />
            )}
          </Card>

          <Card title="سفارش‌های باز">
            {bot.open_orders.length === 0 ? (
              <p className="text-sm text-muted">سفارش بازی وجود ندارد.</p>
            ) : (
              <ul className="space-y-1.5 text-sm">
                {bot.open_orders.map((o) => (
                  <li key={o.id} className="num flex justify-between rounded-lg bg-surface-2 px-3 py-2">
                    <span className={o.side === "buy" ? "text-up" : "text-down"}>{o.side === "buy" ? "خرید" : "فروش"} {o.type === "market" ? "بازار" : "محدود"}</span>
                    <span>{faNum(o.qty, 6)}</span>
                    <span className="text-muted">{o.price ? faNum(o.price, dec) : "—"}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="گزارش تصمیم‌ها" action={status.log[0] && <span className="text-[11px] text-muted">آخرین: {tehranTime(status.log[0].ts)}</span>}>
            <TradeLog entries={status.log} quote={quote} explain={(e) => api.botExplain(e.id).then((r) => r.explanation_fa)} />
          </Card>
        </>
      )}
    </>
  );
}

function ShieldStrip({ log }: { log: BotStatus["log"] }) {
  const blocked = log.filter((e) => !e.decision.approved).length;
  const exits = log.filter((e) => ["stop_loss", "daily_loss_limit"].includes(e.reason) && e.decision.approved).length;
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-primary/30 bg-primary-soft p-3">
      <span className="text-2xl" aria-hidden>
        🛡️
      </span>
      <div className="text-[13px] leading-6">
        <b>سپر ریسک فعال است.</b> تا الان {faNum(blocked, 0)} بار جلوی یک معاملهٔ پرخطر را گرفت و {faNum(exits, 0)} بار با حد ضرر از
        زیان بیشتر جلوگیری کرد.
      </div>
    </div>
  );
}
