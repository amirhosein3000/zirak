"use client";

import { useState } from "react";
import type { LogEntry } from "@/lib/api";
import { faNum, faPct, money, signClass, tehranTime } from "@/lib/fa";
import { Badge, Empty } from "./ui";

const REASON_FA: Record<string, string> = {
  stop_loss: "حد ضرر",
  take_profit: "حد سود",
  daily_loss_limit: "سقف زیان روزانه",
  ema_cross_up: "تقاطع صعودی",
  ema_cross_down: "تقاطع نزولی",
  rsi_oversold: "بیش‌فروش",
  rsi_overbought: "بیش‌خرید",
  grid_buy: "پلهٔ خرید",
  grid_sell: "پلهٔ فروش",
  dca_buy: "خرید دوره‌ای",
  dca_take_profit: "سود سبد",
  rule_entry: "شرط خرید شما",
};

/** Trade log where every row can answer "why did the bot do that?". */
export function TradeLog({
  entries,
  quote,
  explain,
  limit = 30,
}: {
  entries: LogEntry[];
  quote: string;
  explain: (e: LogEntry) => Promise<string>;
  limit?: number;
}) {
  const [open, setOpen] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState<number | null>(null);

  if (!entries.length) return <Empty>هنوز معامله‌ای انجام نشده است.</Empty>;

  async function toggle(e: LogEntry) {
    if (open[e.id] !== undefined) {
      setOpen((o) => {
        const next = { ...o };
        delete next[e.id];
        return next;
      });
      return;
    }
    setLoading(e.id);
    try {
      const text = e.explanation_fa ?? (await explain(e));
      setOpen((o) => ({ ...o, [e.id]: text }));
    } catch (err) {
      setOpen((o) => ({ ...o, [e.id]: (err as Error).message }));
    } finally {
      setLoading(null);
    }
  }

  return (
    <ul className="space-y-2">
      {entries.slice(0, limit).map((e) => {
        const buy = e.side === "buy";
        const approved = e.decision.approved;
        return (
          <li key={e.id} className="rounded-xl bg-surface-2 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Badge tone={!approved ? "muted" : buy ? "up" : "down"}>{buy ? "خرید" : "فروش"}</Badge>
                <span className="text-xs font-bold">{REASON_FA[e.reason] ?? (e.reason.startsWith("rule_exit") ? "شرط خروج" : e.reason)}</span>
                {!approved && <Badge tone="accent">ردشده توسط مدیر ریسک</Badge>}
              </div>
              <span className="text-[11px] text-muted">{tehranTime(e.ts)}</span>
            </div>
            <p className="mt-1.5 text-[13px] leading-6">{e.note_fa}</p>
            <div className="num mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11.5px] text-muted">
              {e.avg_price && <span>قیمت اجرا: {faNum(e.avg_price, quote === "TMN" ? 0 : 2)}</span>}
              {Number(e.filled_qty) > 0 && <span>مقدار: {faNum(e.filled_qty, 6)}</span>}
              {e.pnl !== null && (
                <span className={`font-bold ${signClass(e.pnl)}`}>
                  نتیجه: {money(e.pnl, quote)} {e.pnl_pct !== null && `(${faPct(e.pnl_pct, 1, true)})`}
                </span>
              )}
            </div>
            <button
              onClick={() => toggle(e)}
              className="mt-2 text-xs font-bold text-primary"
              aria-expanded={open[e.id] !== undefined}
            >
              {loading === e.id ? "در حال توضیح…" : open[e.id] !== undefined ? "بستن توضیح" : "چرا این کار را کرد؟"}
            </button>
            {open[e.id] !== undefined && <p className="mt-2 rounded-lg bg-surface p-2.5 text-[13px] leading-6">{open[e.id]}</p>}
          </li>
        );
      })}
    </ul>
  );
}
