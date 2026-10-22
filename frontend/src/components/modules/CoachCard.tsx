"use client";

import { useState } from "react";
import { Badge, Button, Card, ErrorBox } from "@/components/ui";
import { faNum } from "@/lib/fa";
import { modulesApi, type Coach } from "@/lib/modules";

const SEV: Record<string, { tone: "danger" | "accent" | "muted" | "up"; fa: string }> = {
  high: { tone: "danger", fa: "مهم" },
  medium: { tone: "accent", fa: "متوسط" },
  low: { tone: "muted", fa: "کم" },
  good: { tone: "up", fa: "خوب" },
};

export function CoachCard({ symbol }: { symbol: string }) {
  const [c, setC] = useState<Coach | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(source: "bot" | "emotional") {
    setBusy(source);
    setError(null);
    try {
      setC(await modulesApi.coach(source, symbol));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title="مربی معامله‌گری" action={c && <Badge tone={c.score >= 70 ? "up" : c.score >= 40 ? "accent" : "danger"}>انضباط {faNum(c.score, 0)}/۱۰۰</Badge>}>
      <p className="text-sm leading-7 text-muted">زیرک معامله‌ها را مرور می‌کند و عادت‌های پرخطر را با پیشنهاد مشخص نشان می‌دهد.</p>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <Button variant="secondary" loading={busy === "bot"} onClick={() => run("bot")}>
          معامله‌های ربات من
        </Button>
        <Button variant="secondary" loading={busy === "emotional"} onClick={() => run("emotional")}>
          معامله‌گر هیجانی (نمونه)
        </Button>
      </div>
      <div className="mt-3">
        <ErrorBox message={error} />
      </div>
      {c && (
        <div className="mt-3 space-y-2">
          <p className="text-sm leading-7">{c.summary_fa}</p>
          {c.findings.map((f) => (
            <div key={f.code} className="rounded-xl bg-surface-2 p-3 text-sm leading-7">
              <div className="flex items-center justify-between gap-2">
                <b>{f.title_fa}</b>
                <Badge tone={SEV[f.severity].tone}>{SEV[f.severity].fa}</Badge>
              </div>
              <p className="text-xs text-muted">{f.detail_fa}</p>
              <p className="mt-1 text-xs">💡 {f.suggestion_fa}</p>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
