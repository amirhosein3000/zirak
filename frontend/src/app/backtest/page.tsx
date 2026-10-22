"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { ScoreRing } from "@/components/Gauges";
import { DuelBoard } from "@/components/DuelBoard";
import { LineChart, type Marker } from "@/components/LineChart";
import { TradeLog } from "@/components/TradeLog";
import { Badge, Button, Card, Empty, ErrorBox, Skeleton, Stat } from "@/components/ui";
import { api, type PeriodKey, type Report, type RunRequest } from "@/lib/api";
import { RESOLUTION_FA, faNum, faPct, money, signClass, tehranDate } from "@/lib/fa";
import { useAppState } from "@/lib/store";

export default function BacktestPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      <BacktestView />
    </Suspense>
  );
}

function runFromReport(r: Report): RunRequest {
  if (r.meta.spec) return { strategy: "rules", spec: r.meta.spec };
  return { strategy: r.strategy.key, symbol: r.symbol, resolution: r.resolution, params: r.strategy.params };
}

const PERIODS: { key: PeriodKey; label: string }[] = [
  { key: "30d", label: "۳۰ روز" },
  { key: "90d", label: "۹۰ روز" },
  { key: "180d", label: "۶ ماه" },
  { key: "crash", label: "🔥 بدترین ریزش" },
  { key: "all", label: "همه" },
];

function BacktestView() {
  const params = useSearchParams();
  const router = useRouter();
  const [app, setApp] = useAppState();
  const id = params.get("id") ?? app.lastReportId;
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api.report(id).then(setReport).catch((e: Error) => setError(e.message));
  }, [id]);

  if (!id) {
    return (
      <Empty>
        هنوز بک‌تستی اجرا نکرده‌اید. <Link href="/build" className="font-bold text-primary">یک استراتژی بسازید</Link>.
      </Empty>
    );
  }
  if (error && !report) return <ErrorBox message={error} />;
  if (!report || report.id !== id) return <Skeleton className="h-64" />;

  const m = report.metrics;
  const q = report.quote;
  const dec = q === "TMN" ? 0 : 2;
  const curve = report.equity_curve;
  const run = runFromReport(report);

  async function rerun(period: PeriodKey) {
    setBusy(period);
    setError(null);
    try {
      const next = await api.backtest({ ...run, period });
      setApp({ lastReportId: next.id, run });
      router.push(`/backtest?id=${next.id}`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function startPaper() {
    setBusy("paper");
    setError(null);
    try {
      await api.botStart({ ...run, speed_s: 0.5 });
      setApp({ run });
      router.push("/dashboard");
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  const markers: Marker[] = report.trades
    .filter((t) => !t.decision.approved || Number(t.filled_qty) > 0)
    .map((t) => ({ ts: t.ts, side: t.side, label: t.note_fa, blocked: !t.decision.approved }));
  const shield = report.shield;
  const score = report.score;

  return (
    <>
      {/* period chips: re-run the same strategy on another window, incl. the worst crash */}
      <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4" role="group" aria-label="بازهٔ زمانی">
        {PERIODS.map((p) => (
          <button
            key={p.key}
            onClick={() => rerun(p.key)}
            disabled={busy !== null}
            aria-pressed={report.period.key === p.key}
            className={`shrink-0 rounded-full border px-3 py-1.5 text-xs font-bold transition ${
              report.period.key === p.key ? "border-primary bg-primary text-white" : "border-border bg-surface text-muted"
            }`}
          >
            {busy === p.key ? "…" : p.label}
          </button>
        ))}
      </div>
      {report.period.note_fa && <p className="rounded-xl bg-accent/10 p-3 text-[13px] leading-6">🕰️ {report.period.note_fa}</p>}

      {score && (
        <Card>
          <div className="flex items-center gap-4">
            <ScoreRing score={score.score} grade={score.grade} />
            <div className="min-w-0">
              <div className="text-xs text-muted">امتیاز زیرک</div>
              <div className="text-lg font-bold">{score.grade_fa}</div>
              <p className="mt-1 text-[13px] font-bold leading-6">{score.headline_fa}</p>
            </div>
          </div>
          <p className="mt-3 text-[12.5px] leading-6 text-muted">{score.details_fa}</p>
          <div className="mt-3 grid grid-cols-4 gap-1.5 text-center text-[11px]">
            {[
              ["سود", score.components.profit, 20],
              ["حفظ سرمایه", score.components.protection, 30],
              ["برتری", score.components.edge, 35],
              ["ثبات", score.components.consistency, 15],
            ].map(([label, v, max]) => (
              <div key={label as string} className="rounded-lg bg-surface-2 p-1.5">
                <div className="h-1.5 overflow-hidden rounded-full bg-border">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${(Number(v) / Number(max)) * 100}%` }} />
                </div>
                <div className="mt-1 text-muted">{label}</div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {shield && (
        <Card title="🛡️ سپر ریسک زیرک">
          <p className="text-[14px] font-bold leading-7">{shield.message_fa}</p>
          <div className="mt-3 grid grid-cols-2 gap-2">
            <Stat label="با سپر زیرک" value={faPct(shield.with_shield.return_pct, 1, true)} valueClass={signClass(shield.with_shield.return_pct)} hint={`افت: ${faPct(shield.with_shield.max_drawdown_pct, 1)}`} />
            <Stat label="بدون سپر" value={faPct(shield.without_shield.return_pct, 1, true)} valueClass={signClass(shield.without_shield.return_pct)} hint={`افت: ${faPct(shield.without_shield.max_drawdown_pct, 1)}`} />
          </div>
          <p className="mt-2 text-[12px] text-muted">
            {faNum(shield.risk_exits, 0)} خروج با حد ضرر/سقف زیان · {faNum(shield.blocked_orders, 0)} معامله که مدیر ریسک اجازه نداد
          </p>
          {shield.without_curve.length > 1 && (
            <div className="mt-2">
              <LineChart
                ariaLabel="ارزش سرمایه با و بدون سپر ریسک"
                x={curve.map((p) => p.ts)}
                series={[
                  { name: "با سپر", color: "var(--chart-1)", values: curve.map((p) => p.equity) },
                  {
                    name: "بدون سپر",
                    color: "var(--chart-2)",
                    values: curve.map((_, i) => shield.without_curve[Math.min(i, shield.without_curve.length - 1)].equity),
                    dashed: true,
                  },
                ]}
                format={(v) => faNum(v, dec)}
                height={150}
              />
            </div>
          )}
        </Card>
      )}

      <Card
        title={report.strategy.title_fa || report.strategy.key}
        action={<Badge tone={report.meta.data === "synthetic" ? "accent" : "primary"}>{report.meta.data === "synthetic" ? "دادهٔ شبیه‌سازی‌شده" : "دادهٔ واقعی والکس"}</Badge>}
      >
        <p className="text-xs text-muted">
          {report.symbol} · کندل {RESOLUTION_FA[report.resolution] ?? report.resolution} · {tehranDate(report.period.start)} تا{" "}
          {tehranDate(report.period.end)} · سرمایهٔ اولیه {money(report.initial_quote, q)}
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Stat label="بازده استراتژی" value={faPct(m.return_pct, 2, true)} valueClass={signClass(m.return_pct)} hint={money(m.pnl, q)} />
          <Stat label="بازده خرید و نگهداری" value={faPct(m.buy_hold_return_pct, 2, true)} valueClass={signClass(m.buy_hold_return_pct)} />
          <Stat label="بیشترین افت سرمایه" value={faPct(m.max_drawdown_pct, 1)} valueClass="text-down" hint={`نگهداری: ${faPct(m.buy_hold_max_drawdown_pct, 1)}`} />
          <Stat label="نسبت شارپ" value={faNum(m.sharpe, 2)} />
          <Stat label="معاملات سودده" value={faPct(m.win_rate_pct, 0)} hint={`${faNum(m.trades, 0)} معاملهٔ بسته‌شده`} />
          <Stat label="زمان در بازار" value={faPct(m.exposure_pct, 0)} hint={`کارمزد: ${money(m.fees_paid_quote, q)}`} />
        </div>
      </Card>

      <Card title="قیمت و تصمیم‌های ربات">
        <p className="mb-2 text-[11.5px] text-muted">▲ خرید · ▼ فروش · توخالی: مدیر ریسک جلویش را گرفت. انگشت را روی نمودار بکشید.</p>
        <LineChart
          ariaLabel="نمودار قیمت با نشانگر خرید و فروش"
          x={curve.map((p) => p.ts)}
          series={[{ name: "قیمت", color: "var(--chart-1)", values: curve.map((p) => p.price) }]}
          format={(v) => faNum(v, dec)}
          markers={markers}
          height={210}
        />
      </Card>

      <Card title="ارزش سرمایه در برابر نگهداری">
        <LineChart
          ariaLabel="نمودار ارزش سرمایهٔ استراتژی در برابر خرید و نگهداری"
          x={curve.map((p) => p.ts)}
          series={[
            { name: "استراتژی", color: "var(--chart-1)", values: curve.map((p) => p.equity) },
            { name: "نگهداری", color: "var(--chart-2)", values: curve.map((p) => p.buy_hold), dashed: true },
          ]}
          format={(v) => faNum(v, dec)}
        />
      </Card>

      <Card title="افت سرمایه از اوج (٪)">
        <LineChart
          ariaLabel="نمودار افت سرمایه از اوج"
          x={curve.map((p) => p.ts)}
          series={[{ name: "افت", color: "var(--down)", values: curve.map((p) => p.drawdown_pct) }]}
          format={(v) => faPct(v, 1)}
          area
          baseline={0}
          height={130}
        />
      </Card>

      <DuelBoard run={{ ...run, period: report.period.key }} />

      <ErrorBox message={error} />
      <Button className="w-full" onClick={startPaper} loading={busy === "paper"}>
        اجرا در حالت کاغذی (بدون پول واقعی)
      </Button>

      <Card title="معاملات و دلیل هر کدام">
        <TradeLog entries={[...report.trades].reverse()} quote={q} explain={(e) => api.explain(e).then((r) => r.explanation_fa)} />
      </Card>

      <Card title="فرض‌های شبیه‌سازی">
        <ul className="space-y-1 text-[12.5px] leading-6 text-muted">
          <li>
            کارمزد تیکر/میکر: {faPct(report.costs.fee_taker_pct, 2)} / {faPct(report.costs.fee_maker_pct, 2)} (تا اتصال کلید API، مقدار
            پیش‌فرض است)
          </li>
          <li>لغزش قیمت: {faNum(report.costs.slippage_bps, 0)} واحد پایه (bps) در هر سفارش بازار</li>
          <li>
            سفارش‌ها در کندل بعدی اجرا می‌شوند (بدون نگاه به آینده)؛ هر سفارش حداکثر {faPct(Number(report.costs.participation) * 100, 0)} حجم
            کندل را پر می‌کند.
          </li>
        </ul>
      </Card>
    </>
  );
}
