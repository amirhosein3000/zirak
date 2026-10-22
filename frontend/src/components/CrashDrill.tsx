"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Drill, type DrillLine, type DrillScenario, type RunRequest } from "@/lib/api";
import { faNum, faPct, signClass, tehranTime } from "@/lib/fa";
import { LineChart } from "./LineChart";
import { Badge, Button, Card, ErrorBox } from "./ui";

const FALLBACK: DrillScenario[] = [
  { key: "flash_crash", title_fa: "سقوط ناگهانی", story_fa: "" },
  { key: "slow_bleed", title_fa: "ریزش آرام و طولانی", story_fa: "" },
  { key: "pump_dump", title_fa: "پامپ و دامپ", story_fa: "" },
  { key: "gap_down", title_fa: "شکاف قیمتی شبانه", story_fa: "" },
];
const ORDER: DrillLine[] = ["zirak", "naked", "emotional", "hold"];
const STYLE: Record<DrillLine, { color: string; dashed?: boolean; icon: string }> = {
  zirak: { color: "var(--chart-1)", icon: "🛡️" },
  naked: { color: "var(--chart-2)", dashed: true, icon: "🎲" },
  emotional: { color: "var(--down)", icon: "😱" },
  hold: { color: "var(--muted)", dashed: true, icon: "🧊" },
};
const TICK_MS = 70;

/** «مانور سقوط»: what would happen if the market crashed tomorrow? A fire drill, played candle by candle. */
export function CrashDrill({ run }: { run: RunRequest }) {
  const [scenarios, setScenarios] = useState<DrillScenario[]>(FALLBACK);
  const [pick, setPick] = useState("flash_crash");
  const [drill, setDrill] = useState<Drill | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .drillScenarios()
      .then((s) => alive && s.length && setScenarios(s))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  // Playback: one candle per tick until the end.
  useEffect(() => {
    if (!playing || !drill) return;
    timer.current = setInterval(() => {
      setFrame((f) => {
        if (f >= drill.x.length - 1) {
          setPlaying(false);
          return f;
        }
        return f + 1;
      });
    }, TICK_MS);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [playing, drill]);

  async function start(key = pick) {
    setBusy(true);
    setError(null);
    setPick(key);
    try {
      const d = await api.drill({ ...run, scenario: key });
      setDrill(d);
      setFrame(Math.max(1, d.start_index));
      setPlaying(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const domain = useMemo<[number, number] | undefined>(() => {
    if (!drill) return undefined;
    const all = ORDER.flatMap((k) => drill.lines[k]);
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    const pad = (hi - lo) * 0.06 || 1;
    return [lo - pad, hi + pad];
  }, [drill]);

  const scenario = scenarios.find((s) => s.key === pick);
  const done = drill !== null && frame >= drill.x.length - 1;
  const seen = drill ? drill.events.filter((e) => e.i <= frame) : [];
  const latest = seen[seen.length - 1];
  const priceNow = drill ? (drill.price[frame] / drill.price[drill.start_index] - 1) * 100 : 0;
  const inDrill = drill !== null && frame >= drill.start_index;

  return (
    <Card title="🔥 مانور سقوط" action={drill && <Badge tone="accent">قیمت‌های ساختگی</Badge>}>
      <p className="mb-3 text-[13px] leading-6 text-muted">
        اگر بازار <b>فردا</b> سقوط کند چه؟ زیرک آخرین کندل‌های واقعی را برمی‌دارد، یک بحران ساختگی به ادامه‌اش می‌چسباند و استراتژی شما را
        کندل‌به‌کندل در آن می‌اندازد؛ کنار همان استراتژی بدون سپر، یک معامله‌گر هیجانی و کسی که فقط نگه می‌دارد.
      </p>
      <div className="mb-3 flex flex-wrap gap-2" role="radiogroup" aria-label="سناریو">
        {scenarios.map((s) => (
          <button
            key={s.key}
            role="radio"
            aria-checked={pick === s.key}
            disabled={busy}
            onClick={() => (drill ? start(s.key) : setPick(s.key))}
            className={`rounded-full border px-3 py-1.5 text-[13px] font-bold transition ${
              pick === s.key ? "border-down bg-down text-white" : "border-border bg-surface text-muted"
            }`}
          >
            {s.title_fa}
          </button>
        ))}
      </div>
      {scenario?.story_fa && <p className="mb-3 text-[13px] leading-6">{scenario.story_fa}</p>}

      {!drill && (
        <Button className="w-full" variant="danger" loading={busy} onClick={() => start()}>
          شروع مانور
        </Button>
      )}
      <ErrorBox message={error} />

      {drill && domain && (
        <div className="space-y-3">
          <div className={`flex items-baseline justify-between rounded-xl p-3 ${inDrill ? "bg-down/10" : "bg-surface-2"}`} aria-live="polite">
            <span className="text-[13px] text-muted">{inDrill ? "قیمت نسبت به شروع مانور" : "کندل‌های واقعی قبل از مانور"}</span>
            <span className={`num text-xl font-bold ${inDrill ? signClass(priceNow) : ""}`}>
              {inDrill ? faPct(priceNow, 1, true) : tehranTime(drill.x[frame])}
            </span>
          </div>

          <LineChart
            x={drill.x.slice(0, frame + 1)}
            slots={drill.x.length}
            domain={domain}
            height={210}
            endLabels={false}
            series={ORDER.map((k) => ({
              name: drill.titles_fa[k],
              color: STYLE[k].color,
              dashed: STYLE[k].dashed,
              values: drill.lines[k].slice(0, frame + 1),
            }))}
            markers={drill.markers.filter((m) => m.ts <= drill.x[frame])}
            format={(v) => faNum(v - 100, 0) + "٪"}
            ariaLabel="ارزش سرمایه در مانور سقوط (۱۰۰ = شروع)"
          />

          {/* live scoreboard: value of 100 at the start of the playback */}
          <div className="grid grid-cols-2 gap-2">
            {ORDER.map((k) => {
              const v = drill.lines[k][frame] - 100;
              return (
                <div key={k} className={`rounded-xl p-2.5 ${k === "zirak" ? "bg-primary-soft ring-1 ring-primary" : "bg-surface-2"}`}>
                  <div className="truncate text-[11.5px] text-muted">
                    {STYLE[k].icon} {drill.titles_fa[k]}
                  </div>
                  <div className={`num text-[16px] font-bold ${signClass(v)}`}>{faPct(v, 1, true)}</div>
                </div>
              );
            })}
          </div>

          {/* narration ticker */}
          <div className="min-h-16 rounded-xl border border-border p-3 text-[13px] leading-6" aria-live="polite">
            {latest ? (
              <p key={`${latest.i}-${latest.kind}`} className="animate-[fadein_.3s_ease-out]">
                <span className="text-muted">{tehranTime(drill.x[latest.i])} · </span>
                {latest.text_fa}
              </p>
            ) : (
              <p className="text-muted">ربات منتظر است…</p>
            )}
          </div>

          <div className="grid grid-cols-3 gap-2">
            <Button variant="secondary" onClick={() => (done ? (setFrame(Math.max(1, drill.start_index)), setPlaying(true)) : setPlaying(!playing))}>
              {done ? "↺ دوباره" : playing ? "⏸ مکث" : "▶ ادامه"}
            </Button>
            <Button variant="secondary" disabled={done} onClick={() => (setPlaying(false), setFrame(drill.x.length - 1))}>
              ⏭ نتیجه
            </Button>
            <Button variant="ghost" disabled={busy} onClick={() => start(pick)}>
              اجرای مجدد
            </Button>
          </div>

          {done && (
            <div className="space-y-2 rounded-xl bg-surface-2 p-3">
              <p className="text-[14px] font-bold leading-7">{drill.headline_fa}</p>
              {drill.blocked > 0 && (
                <p className="text-[13px] leading-6">
                  🛡️ در طول مانور، مدیر ریسک {faNum(drill.blocked, 0)} بار جلوی خرید را گرفت.
                </p>
              )}
              <details className="text-[13px] leading-6">
                <summary className="cursor-pointer text-primary">همهٔ تصمیم‌ها ({faNum(seen.length, 0)})</summary>
                <ol className="mt-2 space-y-1.5">
                  {seen.map((e, i) => (
                    <li key={i}>
                      <span className="text-muted">{tehranTime(drill.x[e.i])} · </span>
                      {e.text_fa}
                    </li>
                  ))}
                </ol>
              </details>
              <p className="text-[11.5px] text-muted">{drill.note_fa}</p>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}
