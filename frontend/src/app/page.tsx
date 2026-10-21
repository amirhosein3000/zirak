"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LineChart } from "@/components/LineChart";
import { Badge, Card, ErrorBox, Skeleton, Stat } from "@/components/ui";
import { api, type Brief, type CandleRow, type MarketRow } from "@/lib/api";
import { faNum, faPct, money, priceDecimals, signClass, tehranTime } from "@/lib/fa";
import { useAppState } from "@/lib/store";

const TREND = { up: { t: "صعودی", tone: "up" }, down: { t: "نزولی", tone: "down" }, range: { t: "خنثی", tone: "muted" } } as const;
const VOL = { low: "کم", medium: "متوسط", high: "زیاد" } as const;

export default function MarketsPage() {
  const [app, setApp] = useAppState();
  const [markets, setMarkets] = useState<MarketRow[] | null>(null);
  const [detail, setDetail] = useState<{ symbol: string; brief: Brief; candles: CandleRow[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const symbol = app.symbol;

  useEffect(() => {
    api.markets().then(setMarkets).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([api.brief(symbol), api.candles(symbol, "1h", 168)])
      .then(([brief, candles]) => alive && setDetail({ symbol, brief, candles }))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [symbol]);

  // Data for a previously selected market is hidden while the new one loads.
  const current = detail?.symbol === symbol ? detail : null;
  const brief = current?.brief ?? null;
  const candles = current?.candles ?? null;
  const market = markets?.find((m) => m.symbol === symbol);
  const quote = market?.quote ?? "TMN";
  const dec = priceDecimals(quote);

  return (
    <>
      <ErrorBox message={error} />

      <div>
        <h1 className="mb-2 text-base font-bold">یک بازار انتخاب کنید</h1>
        <div className="-mx-4 flex gap-2 overflow-x-auto px-4 pb-1">
          {!markets && [0, 1, 2].map((i) => <Skeleton key={i} className="h-16 w-32 shrink-0" />)}
          {markets?.map((m) => {
            const active = m.symbol === symbol;
            return (
              <button
                key={m.symbol}
                onClick={() => setApp({ symbol: m.symbol })}
                aria-pressed={active}
                className={`min-w-32 shrink-0 rounded-xl border px-3 py-2 text-right transition ${
                  active ? "border-primary bg-primary-soft" : "border-border bg-surface"
                }`}
              >
                <div className="text-sm font-bold">{m.name_fa}</div>
                <div className="num mt-0.5 text-xs text-muted">{faNum(m.price, priceDecimals(m.quote))}</div>
                <div className={`num text-xs font-bold ${signClass(m.change_24h_pct)}`}>{faPct(m.change_24h_pct, 1, true)}</div>
              </button>
            );
          })}
        </div>
      </div>

      <Card
        title={<>تحلیل هوشمند {market?.name_fa ?? ""}</>}
        action={brief && <Badge tone={brief.source === "template" ? "muted" : "primary"}>{brief.source === "template" ? "تحلیل خودکار" : "هوش مصنوعی"}</Badge>}
      >
        {!brief ? (
          <div className="space-y-2">
            <Skeleton className="h-4" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
          </div>
        ) : (
          <>
            <p className="text-[14.5px] leading-7">{brief.brief_fa}</p>
            <p className="mt-2 text-[11px] text-muted">آخرین داده: {tehranTime(brief.as_of)} (به وقت تهران)</p>
          </>
        )}
      </Card>

      {brief && (
        <div className="grid grid-cols-2 gap-2">
          <Stat label="قیمت" value={money(brief.facts.price, quote)} />
          <Stat label="تغییر ۲۴ ساعت" value={faPct(brief.facts.change_24h_pct, 2, true)} valueClass={signClass(brief.facts.change_24h_pct)} />
          <Stat label="روند" value={<Badge tone={TREND[brief.facts.trend].tone}>{TREND[brief.facts.trend].t}</Badge>} />
          <Stat label="نوسان" value={VOL[brief.facts.volatility]} hint={brief.facts.volatility_pct !== null ? `ATR ≈ ${faPct(brief.facts.volatility_pct, 2)}` : undefined} />
          <Stat label="حمایت" value={faNum(brief.facts.support, dec)} />
          <Stat label="مقاومت" value={faNum(brief.facts.resistance, dec)} />
          <Stat label="RSI" value={faNum(brief.facts.rsi14, 0)} />
          <Stat
            label="عدم‌تعادل دفتر سفارش"
            value={faPct(brief.facts.book_imbalance_pct, 0, true)}
            valueClass={signClass(brief.facts.book_imbalance_pct)}
            hint={brief.facts.book_synthetic ? "شبیه‌سازی‌شده" : "+ یعنی خریداران بیشتر"}
          />
        </div>
      )}

      <Card title="قیمت هفتهٔ اخیر (کندل یک‌ساعته)">
        {candles ? (
          <LineChart
            ariaLabel="نمودار قیمت هفتهٔ اخیر"
            x={candles.map((c) => c.ts)}
            series={[{ name: "قیمت", color: "var(--chart-1)", values: candles.map((c) => Number(c.close)) }]}
            format={(v) => faNum(v, dec)}
          />
        ) : (
          <Skeleton className="h-48" />
        )}
      </Card>

      <Link
        href="/build"
        className="flex min-h-12 items-center justify-center rounded-xl bg-primary text-[15px] font-bold text-white"
      >
        ساخت استراتژی برای {market?.name_fa ?? "این بازار"} ←
      </Link>
    </>
  );
}
