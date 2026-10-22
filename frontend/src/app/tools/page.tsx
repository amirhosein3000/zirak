"use client";

import { useEffect, useState } from "react";
import { AlertsCard } from "@/components/modules/AlertsCard";
import { BookCard } from "@/components/modules/BookCard";
import { CoachCard } from "@/components/modules/CoachCard";
import { CompetitionCard } from "@/components/modules/CompetitionCard";
import { NewsCard } from "@/components/modules/NewsCard";
import { PortfolioCard } from "@/components/modules/PortfolioCard";
import { RegimeCard } from "@/components/modules/RegimeCard";
import { Empty, ErrorBox, Skeleton } from "@/components/ui";
import { modulesApi } from "@/lib/modules";
import { useAppState } from "@/lib/store";

const BASE_OF: Record<string, string> = { BTCTMN: "BTC", BTCUSDT: "BTC", ETHTMN: "ETH", ETHUSDT: "ETH", USDTTMN: "USDT" };
const SYMBOLS: [string, string][] = [
  ["BTCTMN", "بیت‌کوین/تومان"],
  ["ETHTMN", "اتریوم/تومان"],
  ["USDTTMN", "تتر/تومان"],
  ["BTCUSDT", "بیت‌کوین/تتر"],
  ["ETHUSDT", "اتریوم/تتر"],
];

export default function ToolsPage() {
  const [app, setApp] = useAppState();
  const [enabled, setEnabled] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const symbol = app.symbol;

  useEffect(() => {
    let alive = true;
    modulesApi
      .list()
      .then((m) => alive && setEnabled(m.enabled))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, []);

  const on = (name: string) => enabled?.includes(name);
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-bold">ابزارهای هوشمند</h1>
        <select
          value={symbol}
          onChange={(e) => setApp({ symbol: e.target.value })}
          className="rounded-lg border border-border bg-surface p-2 text-sm"
          aria-label="بازار"
        >
          {SYMBOLS.map(([s, fa]) => (
            <option key={s} value={s}>
              {fa}
            </option>
          ))}
        </select>
      </div>
      <ErrorBox message={error} />
      {!enabled && !error && <Skeleton className="h-40" />}
      {enabled && enabled.length === 0 && <Empty>هیچ ماژولی فعال نیست (متغیر MODULES در بک‌اند).</Empty>}
      {on("regime") && <RegimeCard symbol={symbol} />}
      {on("orderbook") && <BookCard symbol={symbol} />}
      {on("news") && <NewsCard asset={BASE_OF[symbol]} />}
      {on("coach") && <CoachCard symbol={symbol} />}
      {on("alerts") && <AlertsCard symbol={symbol} />}
      {on("portfolio") && <PortfolioCard />}
      {on("competition") && <CompetitionCard />}
    </>
  );
}
