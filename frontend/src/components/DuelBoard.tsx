"use client";

import { useState } from "react";
import { api, type Duel, type RunRequest } from "@/lib/api";
import { faNum, faPct, signClass } from "@/lib/fa";
import { Button, Card, ErrorBox } from "./ui";

const MEDALS = ["🥇", "🥈", "🥉"];

/** "Duel": your strategy vs the baselines, an emotional trader and buy-and-hold, same market and period. */
export function DuelBoard({ run }: { run: RunRequest }) {
  const [duel, setDuel] = useState<Duel | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      setDuel(await api.duel(run));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="⚔️ دوئل استراتژی‌ها">
      {!duel ? (
        <>
          <p className="mb-3 text-[13px] leading-6 text-muted">
            استراتژی شما را روی همین بازار و همین بازه با چهار استراتژی آماده، «خرید و نگهداری» و یک <b>معامله‌گر هیجانی</b> (که بعد
            از جهش می‌خرد و بعد از ریزش وحشت‌زده می‌فروشد) مقایسه می‌کنیم.
          </p>
          <Button className="w-full" variant="secondary" loading={busy} onClick={go}>
            شروع دوئل
          </Button>
          <ErrorBox message={error} />
        </>
      ) : (
        <>
          <p className="mb-3 text-[14px] font-bold leading-7">{duel.headline_fa}</p>
          <ol className="space-y-1.5">
            {duel.rows.map((r) => (
              <li
                key={r.key}
                className={`flex items-center gap-2 rounded-xl p-2.5 ${
                  r.mine ? "bg-primary-soft ring-1 ring-primary" : r.emotional ? "bg-down/10" : "bg-surface-2"
                }`}
              >
                <span className="w-7 text-center text-base">{MEDALS[r.rank - 1] ?? faNum(r.rank, 0)}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-bold">
                    {r.emotional ? "😱 " : ""}
                    {r.title_fa}
                  </span>
                  <span className="num block text-[11px] text-muted">
                    افت {faPct(r.max_drawdown_pct, 1)} · {faNum(r.trades, 0)} معامله
                  </span>
                </span>
                <span className={`num text-[13px] font-bold ${signClass(r.return_pct)}`}>{faPct(r.return_pct, 1, true)}</span>
                <span className="num w-10 rounded-lg bg-surface px-1.5 py-0.5 text-center text-[12px] font-bold">{faNum(r.score, 0)}</span>
              </li>
            ))}
          </ol>
          <p className="mt-2 text-[11px] text-muted">رتبه‌بندی بر اساس امتیاز زیرک (سود، حفظ سرمایه، برتری بر نگهداری، ثبات).</p>
        </>
      )}
    </Card>
  );
}
