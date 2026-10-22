"use client";

import { useEffect, useState } from "react";
import { Badge, Card, ErrorBox, Skeleton, Stat } from "@/components/ui";
import { faNum, faPct, signClass } from "@/lib/fa";
import { modulesApi, type BookStats, type FairUsdt } from "@/lib/modules";

export function BookCard({ symbol }: { symbol: string }) {
  const [b, setB] = useState<BookStats | null>(null);
  const [fair, setFair] = useState<FairUsdt | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () => {
      modulesApi
        .book(symbol)
        .then((x) => alive && setB(x))
        .catch((e: Error) => alive && setError(e.message));
      modulesApi
        .fairUsdt()
        .then((x) => alive && setFair(x))
        .catch(() => undefined);
    };
    load();
    const t = setInterval(load, 15000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [symbol]);

  return (
    <Card title="هوش دفتر سفارش" action={b?.synthetic && <Badge>شبیه‌سازی‌شده</Badge>}>
      <ErrorBox message={error} />
      {!b && !error && <Skeleton className="h-28" />}
      {b && (
        <div className="space-y-3">
          <p className="text-sm leading-7">{b.summary_fa}</p>
          <div className="grid grid-cols-3 gap-2">
            <Stat label="اسپرد" value={faPct(b.spread_pct, 3)} />
            <Stat label="عدم‌تعادل" value={faPct(b.imbalance_pct, 0, true)} valueClass={signClass(b.imbalance_pct)} />
            <Stat label="دیوارها" value={faNum(b.walls.length, 0)} />
          </div>
          {b.walls.slice(0, 3).map((w, i) => (
            <div key={i} className="flex justify-between rounded-lg bg-surface-2 px-3 py-1.5 text-xs">
              <span className={w.side === "bid" ? "text-up" : "text-down"}>{w.side === "bid" ? "دیوار خرید" : "دیوار فروش"}</span>
              <span className="num">{faNum(w.price, 2)}</span>
              <span className="text-muted">{faNum(w.size_x_median, 1)}× معمول</span>
            </div>
          ))}
        </div>
      )}
      {fair && (
        <div className="mt-3 rounded-xl border border-border p-3 text-sm leading-7">
          <div className="mb-1 text-xs font-bold text-muted">قیمت منصفانهٔ تتر (از بیت‌کوین و اتریوم)</div>
          {fair.summary_fa}
        </div>
      )}
    </Card>
  );
}
