"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, type RunRequest } from "@/lib/api";
import { useAppState } from "@/lib/store";
import { Button, ErrorBox } from "./ui";

/** "Time machine": replay the worst crash in the data with the user's strategy (or a careful default). */
export function TimeMachineButton({ symbol }: { symbol: string }) {
  const router = useRouter();
  const [app, setApp] = useAppState();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function go() {
    setBusy(true);
    setError(null);
    // The user's own rules if they built some for this market, else the classic example sentence:
    // «وقتی ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش» (+ Zirak's 5 % safety stop).
    const base: RunRequest =
      app.spec && app.spec.symbol === symbol
        ? { strategy: "rules", spec: app.spec }
        : {
            strategy: "rules",
            spec: {
              version: 1,
              name: "وقتی ۵٪ ریخت بخر، با ۳٪ سود بفروش",
              symbol,
              resolution: "1h",
              entry: [{ kind: "drop_from_high", pct: 5, lookback: 24 }],
              exit: [],
              position_size_pct: 10,
              take_profit_pct: 3,
              stop_loss_pct: 5,
              max_entries: 1,
              cooldown_candles: 3,
            },
          };
    try {
      const report = await api.backtest({ ...base, period: "crash" });
      setApp({ lastReportId: report.id, run: base });
      router.push(`/backtest?id=${report.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <Button variant="secondary" className="w-full" loading={busy} onClick={go}>
        🕰️ ماشین زمان: زیرک در بدترین ریزش اخیر چه می‌کرد؟
      </Button>
      <ErrorBox message={error} />
    </>
  );
}
