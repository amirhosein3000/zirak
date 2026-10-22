"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, ErrorBox, Stat } from "@/components/ui";
import { faNum, faPct, money, signClass } from "@/lib/fa";
import { modulesApi, type Competition } from "@/lib/modules";

export function CompetitionCard() {
  const [st, setSt] = useState<Competition | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    modulesApi.compStatus().then(setSt).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const t = setTimeout(load, 0);
    const i = setInterval(load, 3000);
    return () => {
      clearTimeout(t);
      clearInterval(i);
    };
  }, [load]);

  async function act(fn: () => Promise<Competition>) {
    setBusy(true);
    setError(null);
    try {
      setSt(await fn());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const start = () => act(async () => modulesApi.compStart({ ...(await modulesApi.compDefault()), speed_s: 0.3, write_every_s: 2 }));

  return (
    <Card title="حالت مسابقه" action={st?.running ? <Badge tone="up">در حال اجرا</Badge> : <Badge>متوقف</Badge>}>
      <p className="text-sm leading-7 text-muted">
        چند استراتژی محافظه‌کار، هرکدام با سهم جدا از سرمایه، به‌صورت کاغذی اجرا می‌شوند. اگر افت کل از سقف بگذرد کلید توقف خودکار زده
        می‌شود. نتیجه در فایل عملکرد ذخیره می‌شود.
      </p>
      <div className="mt-3">
        <ErrorBox message={error} />
      </div>
      {st && st.entries.length > 0 && (
        <div className="mt-3 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <Stat label="ارزش کل (تومان)" value={faNum(st.total_equity_tmn, 0)} />
            <Stat
              label="سود / زیان"
              value={faPct(st.pnl_pct, 2, true)}
              valueClass={signClass(st.pnl_pct)}
              hint={`افت از اوج ${faPct(st.drawdown_from_peak_pct, 2)} (سقف ${faPct(st.limits?.max_drawdown_pct, 0)})`}
            />
          </div>
          {st.stopped_reason && <p className="text-xs text-danger">توقف خودکار: {st.stopped_reason}</p>}
          {st.entries.map((e) => (
            <div key={e.name} className="flex items-center justify-between gap-2 rounded-lg bg-surface-2 px-3 py-2 text-xs">
              <span>
                <b>{e.name}</b> · {e.symbol}
              </span>
              <span className="num">{money(e.equity, e.quote)}</span>
              <span className={`num font-bold ${signClass(e.pnl_pct)}`}>{faPct(e.pnl_pct, 2, true)}</span>
              <span className="text-muted">{faNum(e.trades, 0)} معامله</span>
            </div>
          ))}
        </div>
      )}
      <div className="mt-3 grid grid-cols-2 gap-2">
        {st?.running ? (
          <Button variant="secondary" loading={busy} onClick={() => act(modulesApi.compStop)}>
            توقف عادی
          </Button>
        ) : (
          <Button loading={busy} onClick={start} disabled={st?.kill_engaged}>
            شروع مسابقهٔ کاغذی
          </Button>
        )}
        <Button variant="danger" loading={busy} onClick={() => act(modulesApi.compKill)}>
          ⏻ توقف اضطراری
        </Button>
      </div>
    </Card>
  );
}
