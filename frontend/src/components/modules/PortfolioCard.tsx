"use client";

import { useState } from "react";
import { LineChart } from "@/components/LineChart";
import { Button, Card, ErrorBox, Stat } from "@/components/ui";
import { faNum, faPct, signClass, tehranDate } from "@/lib/fa";
import { modulesApi, type PortfolioResult } from "@/lib/modules";

const ASSETS: [string, string][] = [
  ["TMN", "تومان"],
  ["USDT", "تتر"],
  ["BTC", "بیت‌کوین"],
  ["ETH", "اتریوم"],
];

export function PortfolioCard() {
  const [targets, setTargets] = useState<Record<string, number>>({ TMN: 20, USDT: 30, BTC: 30, ETH: 20 });
  const [threshold, setThreshold] = useState(5);
  const [res, setRes] = useState<PortfolioResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sum = Object.values(targets).reduce((a, b) => a + b, 0);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      setRes(await modulesApi.portfolio(targets, threshold));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="سبد هدف و متعادل‌سازی">
      <div className="grid grid-cols-4 gap-2">
        {ASSETS.map(([a, fa]) => (
          <label key={a} className="text-center text-xs text-muted">
            {fa}
            <input
              type="number"
              min={0}
              max={100}
              inputMode="numeric"
              value={targets[a]}
              onChange={(e) => setTargets({ ...targets, [a]: Number(e.target.value) || 0 })}
              className="num mt-1 w-full rounded-lg border border-border bg-surface-2 p-2 text-center text-sm text-text"
            />
          </label>
        ))}
      </div>
      <label className="mt-3 flex items-center justify-between text-xs text-muted">
        متعادل‌سازی وقتی سهمی بیش از این مقدار از هدف دور شود (٪):
        <input
          type="number"
          min={1}
          max={50}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value) || 5)}
          className="num w-16 rounded-lg border border-border bg-surface-2 p-1.5 text-center text-sm text-text"
        />
      </label>
      {sum !== 100 && <p className="mt-2 text-xs text-danger">جمع سهم‌ها باید ۱۰۰ باشد (اکنون {faNum(sum, 0)}).</p>}
      <Button className="mt-3 w-full" loading={busy} disabled={sum !== 100} onClick={run}>
        آزمون روی داده‌های گذشته
      </Button>
      <div className="mt-3">
        <ErrorBox message={error} />
      </div>
      {res && (
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Stat
              label="با متعادل‌سازی"
              value={faPct(res.rebalanced.return_pct, 1, true)}
              valueClass={signClass(res.rebalanced.return_pct)}
              hint={`افت ${faPct(res.rebalanced.max_drawdown_pct, 1)} · ${faNum(res.rebalances.length, 0)} بار`}
            />
            <Stat
              label="بدون متعادل‌سازی"
              value={faPct(res.hold.return_pct, 1, true)}
              valueClass={signClass(res.hold.return_pct)}
              hint={`افت ${faPct(res.hold.max_drawdown_pct, 1)}`}
            />
          </div>
          <LineChart
            x={res.curve.map((p) => p.ts)}
            series={[
              { name: "متعادل", values: res.curve.map((p) => p.rebalanced), color: "var(--chart-1)" },
              { name: "نگهداری", values: res.curve.map((p) => p.hold), color: "var(--chart-2)", dashed: true },
            ]}
            format={(v) => faNum(v, 0)}
            ariaLabel="ارزش سبد"
          />
          <p className="text-xs text-muted">کارمزد کل: {faNum(res.fees_tmn, 0)} تومان · قیمت اجرا: باز شدن کندل بعد با لغزش</p>
          {res.rebalances.slice(-3).reverse().map((r, i) => (
            <div key={i} className="rounded-xl bg-surface-2 p-3 text-xs leading-6">
              <div className="mb-1 font-bold text-muted">{tehranDate(r.ts)}</div>
              {r.note_fa}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
