"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { LineChart } from "@/components/LineChart";
import { TradeLog } from "@/components/TradeLog";
import { Badge, Button, Card, Empty, ErrorBox, Skeleton, Stat } from "@/components/ui";
import { api, type Report, type RunRequest } from "@/lib/api";
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

function BacktestView() {
  const params = useSearchParams();
  const router = useRouter();
  const [app, setApp] = useAppState();
  const id = params.get("id") ?? app.lastReportId;
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

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
  if (error) return <ErrorBox message={error} />;
  if (!report) return <Skeleton className="h-64" />;

  const m = report.metrics;
  const q = report.quote;
  const beat = m.return_pct > m.buy_hold_return_pct;
  const safer = m.max_drawdown_pct > m.buy_hold_max_drawdown_pct;
  const curve = report.equity_curve;

  async function startPaper() {
    setStarting(true);
    setError(null);
    try {
      await api.botStart({ ...runFromReport(report!), speed_s: 0.5 });
      setApp({ run: runFromReport(report!) });
      router.push("/dashboard");
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  return (
    <>
      <Card
        title={report.strategy.title_fa || report.strategy.key}
        action={<Badge tone={report.meta.data === "sample" ? "accent" : "primary"}>{report.meta.data === "sample" ? "دادهٔ شبیه‌سازی‌شده" : "دادهٔ واقعی ضبط‌شده"}</Badge>}
      >
        <p className="text-xs text-muted">
          {report.symbol} · کندل {RESOLUTION_FA[report.resolution] ?? report.resolution} · {tehranDate(report.period.start)} تا {tehranDate(report.period.end)} ·{" "}
          {faNum(report.period.candles, 0)} کندل · سرمایهٔ اولیه {money(report.initial_quote, q)}
        </p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          <Stat label="بازده استراتژی" value={faPct(m.return_pct, 2, true)} valueClass={signClass(m.return_pct)} hint={money(m.pnl, q)} />
          <Stat label="بازده خرید و نگهداری" value={faPct(m.buy_hold_return_pct, 2, true)} valueClass={signClass(m.buy_hold_return_pct)} />
          <Stat label="بیشترین افت سرمایه" value={faPct(m.max_drawdown_pct, 1)} valueClass="text-down" hint={`خرید و نگهداری: ${faPct(m.buy_hold_max_drawdown_pct, 1)}`} />
          <Stat label="نسبت شارپ" value={faNum(m.sharpe, 2)} />
          <Stat label="درصد معاملات سودده" value={faPct(m.win_rate_pct, 0)} hint={`${faNum(m.trades, 0)} معاملهٔ بسته‌شده`} />
          <Stat label="زمان در بازار" value={faPct(m.exposure_pct, 0)} hint={`کارمزد: ${money(m.fees_paid_quote, q)}`} />
        </div>
        <p className="mt-3 rounded-xl bg-surface-2 p-3 text-[13px] leading-6">
          {beat ? "این استراتژی در این دوره از خرید و نگهداری بهتر بود" : "این استراتژی در این دوره از خرید و نگهداری ضعیف‌تر بود"}
          {safer ? "، و افت سرمایهٔ کمتری داشت (ریسک کمتر)." : "، و افت سرمایه‌اش کمتر نبود."} نتایج گذشته تضمینی برای آینده نیست.
        </p>
      </Card>

      <Card title="ارزش سرمایه">
        <LineChart
          ariaLabel="نمودار ارزش سرمایهٔ استراتژی در برابر خرید و نگهداری"
          x={curve.map((p) => p.ts)}
          series={[
            { name: "استراتژی", color: "var(--chart-1)", values: curve.map((p) => p.equity) },
            { name: "نگهداری", color: "var(--chart-2)", values: curve.map((p) => p.buy_hold), dashed: true },
          ]}
          format={(v) => faNum(v, q === "TMN" ? 0 : 2)}
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
          height={140}
        />
      </Card>

      <ErrorBox message={error} />
      <Button className="w-full" onClick={startPaper} loading={starting}>
        اجرا در حالت کاغذی (بدون پول واقعی)
      </Button>

      <Card title="معاملات و دلیل هر کدام">
        <TradeLog
          entries={[...report.trades].reverse()}
          quote={q}
          explain={(e) => api.explain(e).then((r) => r.explanation_fa)}
        />
      </Card>

      <Card title="فرض‌های شبیه‌سازی">
        <ul className="space-y-1 text-[12.5px] leading-6 text-muted">
          <li>کارمزد تیکر/میکر: {faPct(report.costs.fee_taker_pct, 2)} / {faPct(report.costs.fee_maker_pct, 2)} (قابل تنظیم؛ هنوز با جدول کارمزد صرافی تطبیق داده نشده)</li>
          <li>لغزش قیمت: {faNum(report.costs.slippage_bps, 0)} واحد پایه (bps) در هر سفارش بازار</li>
          <li>سفارش‌ها در کندل بعدی اجرا می‌شوند (بدون نگاه به آینده)؛ هر سفارش حداکثر {faPct(Number(report.costs.participation) * 100, 0)} حجم کندل را پر می‌کند.</li>
          <li>مدیریت ریسک: {Object.entries(report.risk).filter(([, v]) => v !== null).map(([k, v]) => `${k}=${v}`).join("، ")}</li>
        </ul>
      </Card>
    </>
  );
}
