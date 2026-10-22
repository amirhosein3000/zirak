"use client";

import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorBox, Skeleton } from "@/components/ui";
import { faNum, faPct, signClass } from "@/lib/fa";
import { modulesApi, type GatedResult, type Regime } from "@/lib/modules";

const TONE: Record<Regime["regime"], "up" | "down" | "accent" | "danger"> = {
  trending_up: "up",
  trending_down: "down",
  ranging: "accent",
  volatile: "danger",
};
const STRAT_FA: Record<string, string> = { ema_cross: "تقاطع میانگین‌ها", rsi_reversion: "RSI", grid: "گرید", dca: "خرید دوره‌ای" };

export function RegimeCard({ symbol }: { symbol: string }) {
  const [r, setR] = useState<Regime | null>(null);
  const [gated, setGated] = useState<GatedResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    modulesApi
      .regime(symbol)
      .then((x) => alive && (setR(x), setGated(null)))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [symbol]);

  async function compare() {
    setBusy(true);
    setError(null);
    try {
      setGated(await modulesApi.regimeBacktest(symbol, "ema_cross", ["trending_up"]));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="حالت بازار" action={r && <Badge tone={TONE[r.regime]}>{r.label_fa}</Badge>}>
      <ErrorBox message={error} />
      {!r && !error && <Skeleton className="h-20" />}
      {r && (
        <div className="space-y-2 text-sm leading-7">
          <p>{r.advice_fa}</p>
          <p className="text-xs text-muted">
            کارایی روند {faNum(r.efficiency, 2)} · شیب میانگین ۵۰ {faPct(r.slope_pct, 2, true)} · نوسان {faPct(r.atr_pct, 2)} (
            {faNum(r.atr_ratio, 1)} برابر حالت معمول)
          </p>
          {r.suits.length > 0 && (
            <p className="text-xs">مناسب برای: {r.suits.map((s) => STRAT_FA[s] ?? s).join("، ")}</p>
          )}
          <Button variant="secondary" className="w-full" loading={busy} onClick={compare}>
            آزمون: تقاطع میانگین‌ها فقط در روند صعودی
          </Button>
          {gated && (
            <div className="grid grid-cols-2 gap-2 text-center text-xs">
              {(["plain", "gated"] as const).map((k) => (
                <div key={k} className="rounded-xl bg-surface-2 p-2">
                  <div className="text-muted">{k === "plain" ? "همیشه فعال" : "فقط در روند صعودی"}</div>
                  <div className={`num text-base font-bold ${signClass(gated[k].return_pct)}`}>{faPct(gated[k].return_pct, 1, true)}</div>
                  <div className="text-muted">
                    افت {faPct(gated[k].max_drawdown_pct, 1)} · {faNum(gated[k].trades, 0)} معامله
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
