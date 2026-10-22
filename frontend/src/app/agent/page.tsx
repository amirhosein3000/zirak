"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { LineChart } from "@/components/LineChart";
import { Badge, Card, Empty, ErrorBox, Skeleton, Stat } from "@/components/ui";
import { agentApi, type Decision, type RunRow, type RunSummary } from "@/lib/agent";
import { faNum, faPct, signClass, tehranTime } from "@/lib/fa";

const MODE_FA: Record<string, string> = { live: "معاملهٔ واقعی", shadow: "تست سایه", backtest: "بک‌تست" };
const SETUP_FA: Record<string, string> = {
  mean_reversion: "بازگشت به میانگین",
  breakout: "شکست سقف با حجم",
  basis_reversion: "جاماندن از نرخ جهانی",
  trend_pullback: "اصلاح در روند",
  adopted: "دارایی بازیابی‌شده",
};
const STANCE: Record<string, { fa: string; tone: "up" | "accent" | "danger" }> = {
  normal: { fa: "عادی", tone: "up" },
  cautious: { fa: "محتاط", tone: "accent" },
  avoid: { fa: "پرهیز", tone: "danger" },
};
const GUARD_FA: Record<string, string> = {
  ok: "عادی",
  pause: "توقف ورود",
  flatten: "در حال تبدیل به تومان",
  flatten_hard: "فروش فوری پایان چالش",
  kill: "توقف اضطراری",
  killed: "متوقف",
};

export default function AgentPage() {
  const [runs, setRuns] = useState<RunRow[] | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [data, setData] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    agentApi
      .runs()
      .then((r) => {
        if (!alive) return;
        setRuns(r);
        setName((n) => n ?? r[0]?.run ?? null);
      })
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, []);

  const load = useCallback(() => {
    if (!name) return;
    agentApi
      .run(name)
      .then((d) => (setData(d), setError(null)))
      .catch((e: Error) => setError(e.message));
  }, [name]);

  useEffect(() => {
    const t = setTimeout(load, 0);
    const i = setInterval(load, 10000);
    return () => {
      clearTimeout(t);
      clearInterval(i);
    };
  }, [load]);

  if (runs && runs.length === 0)
    return (
      <Empty>
        هنوز اجرایی از عامل معاملاتی ثبت نشده است. در بک‌اند اجرا کنید: <span dir="ltr">zirak agent backtest</span>
      </Empty>
    );

  const r = data?.report;
  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <h1 className="text-lg font-bold">عامل معاملاتی زیرک</h1>
        {data && <Badge tone={data.mode === "live" ? "danger" : data.mode === "shadow" ? "accent" : "muted"}>{MODE_FA[data.mode]}</Badge>}
      </div>
      {runs && runs.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1">
          {runs.map((x) => (
            <button
              key={x.run}
              onClick={() => setName(x.run)}
              aria-pressed={x.run === name}
              className={`shrink-0 rounded-full border px-3 py-1 text-xs font-bold ${x.run === name ? "border-primary bg-primary text-white" : "border-border bg-surface text-muted"}`}
            >
              {MODE_FA[x.mode] ?? x.mode} · <span dir="ltr">{x.run}</span>
            </button>
          ))}
        </div>
      )}
      <ErrorBox message={error} />
      {!data && !error && <Skeleton className="h-64" />}
      {data && r && (
        <>
          <Card title="نتیجه" action={data.guard && <Badge tone={data.guard.last_status === "ok" ? "up" : "danger"}>{GUARD_FA[data.guard.last_status.split(":")[0]] ?? data.guard.last_status}</Badge>}>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="بازده تحقق‌یافته (تومان)" value={faPct(r.realized_return_pct, 2, true)} valueClass={signClass(r.realized_return_pct)} hint={`${faNum(r.realized_pnl_tmn, 0)} تومان`} />
              <Stat label="بازده با ارزش لحظه‌ای" value={faPct(r.return_pct, 2, true)} valueClass={signClass(r.return_pct)} hint={`${faNum(r.end_equity_tmn, 0)} تومان`} />
              <Stat label="بیشترین افت سرمایه" value={faPct(-r.max_drawdown_pct, 2)} valueClass="text-down" />
              <Stat label="معاملات (رفت و برگشت)" value={faNum(r.trades, 0)} hint={r.win_rate_pct !== null ? `برد ${faPct(r.win_rate_pct, 0)}` : undefined} />
              <Stat label="حجم معاملات" value={faNum(r.volume_tmn, 0)} hint={r.avg_trade_volume_tmn ? `میانگین ${faNum(r.avg_trade_volume_tmn, 0)}` : undefined} />
              <Stat label="پایداری" value={`${faNum(r.stability.errors, 0)} خطا`} hint={`${faNum(r.stability.orders, 0)} سفارش · تأخیر ${r.speed.order_ack_ms_p50 === null ? "—" : faNum(r.speed.order_ack_ms_p50, 0) + " ms"}`} />
            </div>
            <p className="mt-3 text-xs text-muted">
              {r.period.start && `${tehranTime(r.period.start)} تا ${r.period.end ? tehranTime(r.period.end) : "اکنون"}`} · کندل {data.config.resolution} ·{" "}
              {data.config.markets.join("، ")} {data.commit && <span dir="ltr">· {data.commit.slice(0, 8)}</span>}
            </p>
          </Card>

          {data.equity.length > 1 && (
            <Card title="ارزش حساب (تومان)">
              <LineChart
                x={data.equity.map((p) => p.ts)}
                series={[{ name: "ارزش حساب", color: "var(--chart-1)", values: data.equity.map((p) => p.equity) }]}
                format={(v) => faNum(v, 0)}
                ariaLabel="ارزش حساب"
                area
              />
            </Card>
          )}

          <Card title="هوش مصنوعی در تصمیم‌ها">
            <div className="grid grid-cols-2 gap-2">
              <Stat label="فرصت‌های بررسی‌شده" value={faNum(r.ai.candidates, 0)} />
              <Stat label="تأییدشده و خریده‌شده" value={faNum(r.ai.taken, 0)} valueClass="text-up" />
              <Stat label="ردشده توسط مدل یادگیری ماشین" value={faNum(r.ai.skipped_by_model, 0)} />
              <Stat label="ردشده توسط عامل زبانی" value={faNum(r.ai.skipped_by_posture, 0)} />
            </div>
          </Card>

          {data.posture && (
            <Card title="وضعیت ریسک هر بازار" action={<Badge tone={data.posture.source.startsWith("llm") ? "primary" : "muted"}>{data.posture.source.startsWith("llm") ? "مدل زبانی" : "قواعد ثابت"}</Badge>}>
              {data.posture.summary_fa && <p className="mb-2 text-sm leading-7">{data.posture.summary_fa}</p>}
              <div className="space-y-1.5">
                {Object.entries(data.posture.markets).map(([sym, mp]) => (
                  <div key={sym} className="rounded-xl bg-surface-2 p-2.5 text-xs leading-6">
                    <div className="flex items-center justify-between">
                      <b dir="ltr">{sym}</b>
                      <span className="flex items-center gap-2">
                        <span className="num">×{faNum(mp.risk_multiplier, 2)}</span>
                        <Badge tone={STANCE[mp.stance]?.tone ?? "muted"}>{STANCE[mp.stance]?.fa ?? mp.stance}</Badge>
                      </span>
                    </div>
                    <p className="text-muted">{mp.reason_fa}</p>
                  </div>
                ))}
              </div>
              {data.posture.tool_calls.length > 0 && (
                <p className="mt-2 text-[11px] text-muted" dir="ltr">
                  tools: {data.posture.tool_calls.map((t) => t.name).join(", ")}
                </p>
              )}
            </Card>
          )}

          <Card title="موقعیت‌های باز">
            {data.positions.length === 0 ? (
              <Empty>موقعیت بازی وجود ندارد؛ همهٔ سرمایه به تومان است.</Empty>
            ) : (
              data.positions.map((p) => (
                <div key={p.symbol} className="mb-1.5 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-surface-2 p-2.5 text-xs">
                  <b dir="ltr">{p.symbol}</b>
                  <span>{SETUP_FA[p.setup] ?? p.setup}</span>
                  <span className="num">ورود {faNum(p.entry_price, 0)}</span>
                  <span className="num text-up">سود {faNum(p.take_profit, 0)}</span>
                  <span className="num text-down">ضرر {faNum(p.stop, 0)}</span>
                </div>
              ))
            )}
          </Card>

          <Card title="لاگ تصمیم‌ها (جدیدترین اول)">
            <ol className="space-y-1.5">
              {data.decisions.map((d) => (
                <DecisionRow key={d.id} d={d} run={data.run} />
              ))}
            </ol>
          </Card>
          <p className="text-center text-xs text-muted">
            همهٔ تصمیم‌ها با <span dir="ltr">zirak agent verify</span> از روی همین لاگ‌ها دوباره محاسبه و تأیید می‌شوند. ·{" "}
            <Link href="/safety" className="text-primary">
              ایمنی و پیش‌پرواز
            </Link>
          </p>
        </>
      )}
    </>
  );
}

function DecisionRow({ d, run }: { d: Decision; run: string }) {
  const [open, setOpen] = useState(false);
  const [follow, setFollow] = useState<Decision[] | null>(null);
  const tone = d.kind === "candidate" ? (d.action === "buy" ? "up" : "muted") : d.kind === "exit" ? (Number(d.pnl_tmn) >= 0 ? "up" : "down") : d.kind === "guard" || d.kind === "kill" ? "danger" : "primary";
  const label =
    d.kind === "candidate" ? (d.action === "buy" ? "خرید" : "رد شد") : d.kind === "exit" ? "خروج" : d.kind === "entry_filled" ? "پر شد" : d.kind === "guard" ? "محافظ" : d.kind === "kill" ? "توقف" : "بازیابی";
  async function toggle() {
    setOpen(!open);
    if (!open && follow === null && d.kind === "candidate" && d.action === "buy") {
      agentApi
        .decision(run, d.id)
        .then((x) => setFollow(x.follow_ups))
        .catch(() => setFollow([]));
    }
  }
  return (
    <li className="rounded-xl bg-surface-2 p-2.5 text-xs leading-6">
      <button className="w-full text-start" onClick={toggle} aria-expanded={open}>
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <Badge tone={tone}>{label}</Badge>
            {d.symbol && <b dir="ltr">{d.symbol}</b>}
            {d.setup && <span>{SETUP_FA[d.setup] ?? d.setup}</span>}
          </span>
          <span className="text-muted">{tehranTime(d.ts)}</span>
        </div>
        {d.model && (
          <div className="num text-muted">
            احتمال {faPct(d.model.prob * 100, 0)} · ارزش مورد انتظار {faPct(d.model.ev_pct, 2, true)}
            {d.posture && ` · عامل: ${STANCE[d.posture.stance]?.fa ?? d.posture.stance} ×${faNum(d.posture.mult, 2)}`}
          </div>
        )}
        {d.kind === "exit" && d.pnl_pct && <div className={`num font-bold ${signClass(d.pnl_pct)}`}>{faPct(d.pnl_pct, 2, true)}</div>}
        <p>{d.reason_fa}</p>
      </button>
      {open && (
        <div className="mt-2 space-y-1 border-t border-border pt-2 text-[11px] text-muted">
          {d.signal_fa && <p>سیگنال: {d.signal_fa}</p>}
          {d.model && <p dir="ltr">model {d.model.id} ({d.model.source}): {d.model.why}</p>}
          {d.posture?.reason_fa && <p>عامل زبانی: {d.posture.reason_fa}</p>}
          {d.risk && (
            <p>
              ریسک: {faNum(d.risk.risk_tmn, 0)} تومان · حجم {faNum(d.risk.value_tmn, 0)} تومان · محدودکننده: <span dir="ltr">{d.risk.bound_by}</span>
            </p>
          )}
          {d.indicators && <p dir="ltr">{Object.entries(d.indicators).map(([k, v]) => `${k}=${typeof v === "number" ? Number(v.toFixed(3)) : v}`).join("  ")}</p>}
          {follow?.map((f) => (
            <p key={f.id}>
              ↳ {tehranTime(f.ts)}: {f.reason_fa}
            </p>
          ))}
        </div>
      )}
    </li>
  );
}
