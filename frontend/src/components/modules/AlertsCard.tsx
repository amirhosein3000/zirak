"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox } from "@/components/ui";
import { faNum, tehranTime } from "@/lib/fa";
import { modulesApi, type Alerts } from "@/lib/modules";

export function AlertsCard({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Alerts | null>(null);
  const [kind, setKind] = useState("price_below");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    modulesApi.alerts().then(setData).catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => {
    const t = setTimeout(load, 0);
    const i = setInterval(load, 20000);
    return () => {
      clearTimeout(t);
      clearInterval(i);
    };
  }, [load]);

  async function add() {
    const v = Number(value.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/[,٬]/g, ""));
    if (!Number.isFinite(v) || value.trim() === "") {
      setError("یک عدد معتبر وارد کنید.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await modulesApi.addAlert({ symbol, kind, value: v, once: true });
      setValue("");
      await modulesApi.checkAlerts();
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const kinds = data?.kinds_fa ?? {};
  return (
    <Card
      title="هشدارها"
      action={
        <div className="flex gap-1">
          <Badge tone={data?.channels.telegram ? "primary" : "muted"}>تلگرام</Badge>
          <Badge tone={data?.channels.bale ? "primary" : "muted"}>بله</Badge>
        </div>
      }
    >
      <div className="flex gap-2">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="min-w-0 flex-1 rounded-lg border border-border bg-surface-2 p-2 text-sm"
          aria-label="نوع هشدار"
        >
          {Object.entries(kinds).map(([k, fa]) => (
            <option key={k} value={k}>
              {fa}
            </option>
          ))}
        </select>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          inputMode="decimal"
          placeholder="مقدار"
          className="num w-28 rounded-lg border border-border bg-surface-2 p-2 text-center text-sm"
          aria-label="مقدار"
        />
      </div>
      <Button className="mt-2 w-full" variant="secondary" loading={busy} onClick={add}>
        افزودن هشدار برای {symbol}
      </Button>
      <div className="mt-2">
        <ErrorBox message={error} />
      </div>
      <div className="mt-3 space-y-1.5">
        {data && data.alerts.length === 0 && <Empty>هنوز هشداری نساخته‌اید.</Empty>}
        {data?.alerts.map((a) => (
          <div key={a.id} className="flex items-center justify-between gap-2 rounded-lg bg-surface-2 px-3 py-1.5 text-xs">
            <span>
              {a.kind === "pnl_below_pct" ? "ربات" : a.symbol} · {kinds[a.kind] ?? a.kind} <span className="num">{faNum(a.value, 2)}</span>
            </span>
            <span className="flex items-center gap-2">
              {a.active ? <Badge tone="primary">فعال</Badge> : <Badge>اجرا شد</Badge>}
              <button className="text-danger" onClick={() => modulesApi.deleteAlert(a.id).then(load)} aria-label="حذف هشدار">
                ✕
              </button>
            </span>
          </div>
        ))}
      </div>
      {data && data.events.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <div className="text-xs font-bold text-muted">آخرین هشدارها</div>
          {data.events.slice(0, 5).map((e, i) => (
            <div key={i} className="rounded-lg border border-border px-3 py-1.5 text-xs leading-6">
              <span className="text-muted">{tehranTime(e.ts)} · </span>
              {e.message_fa}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
