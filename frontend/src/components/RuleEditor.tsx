"use client";

// Visual strategy builder: the StrategySpec as blocks (market, timeframe, conditions, money rules).
// It only edits JSON; the backend validates it and describes it in Persian before anything runs.

import type { Condition, ConditionField, StrategySpec, Vocabulary } from "@/lib/api";
import { faNum } from "@/lib/fa";

export const BLANK_SPEC: StrategySpec = {
  version: 1,
  name: "استراتژی من",
  symbol: "BTCTMN",
  resolution: "1h",
  entry: [{ kind: "drop_from_high", pct: 3, minutes: 1440 }],
  exit: [],
  position_size_pct: 10,
  take_profit_pct: 3,
  stop_loss_pct: 5,
  max_entries: 1,
  cooldown_candles: 3,
};

const KIND_DEFAULTS: Record<string, Partial<Condition>> = {
  drop_from_high: { pct: 3, minutes: 1440 },
  rise_from_low: { pct: 3, minutes: 1440 },
  rsi_below: { value: 30, period: 14 },
  rsi_above: { value: 70, period: 14 },
  ema_cross_up: { fast: 12, slow: 26 },
  ema_cross_down: { fast: 12, slow: 26 },
  price_below: { value: 1 },
  price_above: { value: 1 },
};

const FIELD_FA: Record<ConditionField, { label: string; suffix?: string }> = {
  pct: { label: "حداقل", suffix: "٪" },
  minutes: { label: "در بازهٔ" },
  value: { label: "مقدار" },
  period: { label: "دورهٔ RSI", suffix: "کندل" },
  fast: { label: "میانگین سریع", suffix: "کندل" },
  slow: { label: "میانگین کند", suffix: "کندل" },
};

const WINDOWS = [5, 15, 30, 60, 120, 240, 720, 1440, 4320, 10080];
const RES_MINUTES: Record<string, number> = { "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440 };

export function windowFa(minutes: number): string {
  if (minutes % 1440 === 0) return `${faNum(minutes / 1440, 0)} روز`;
  if (minutes % 60 === 0) return `${faNum(minutes / 60, 0)} ساعت`;
  return `${faNum(minutes, 0)} دقیقه`;
}

const inputCls = "min-h-10 w-full rounded-lg border border-border bg-surface px-2 text-sm outline-none focus:border-primary";

function NumberInput({ value, onChange, suffix, label, allowEmpty = false }: {
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  suffix?: string;
  label: string;
  allowEmpty?: boolean;
}) {
  return (
    <label className="block min-w-0 flex-1 text-[11.5px] text-muted">
      {label}
      <div className="mt-1 flex items-center gap-1">
        <input
          type="number"
          inputMode="decimal"
          dir="ltr"
          className={inputCls}
          value={value ?? ""}
          placeholder={allowEmpty ? "خالی = ندارد" : undefined}
          onChange={(e) => {
            const raw = e.target.value.trim();
            if (raw === "") onChange(allowEmpty ? null : 0);
            else if (Number.isFinite(Number(raw))) onChange(Number(raw));
          }}
        />
        {suffix && <span className="shrink-0 text-xs">{suffix}</span>}
      </div>
    </label>
  );
}

function ConditionRow({ cond, vocab, resolution, onChange, onRemove }: {
  cond: Condition;
  vocab: Vocabulary;
  resolution: string;
  onChange: (c: Condition) => void;
  onRemove?: () => void;
}) {
  const meta = vocab.conditions.find((c) => c.kind === cond.kind);
  const minutes = cond.minutes ?? (cond.lookback ? cond.lookback * RES_MINUTES[resolution] : 1440);
  const windows = WINDOWS.filter((w) => w >= RES_MINUTES[resolution]);
  return (
    <div className="rounded-xl border border-border bg-surface-2 p-3">
      <div className="flex items-center gap-2">
        <select
          aria-label="نوع شرط"
          className={inputCls}
          value={cond.kind}
          onChange={(e) => onChange({ kind: e.target.value, ...KIND_DEFAULTS[e.target.value] })}
        >
          {vocab.conditions.map((c) => (
            <option key={c.kind} value={c.kind}>
              {c.title_fa}
            </option>
          ))}
        </select>
        {onRemove && (
          <button onClick={onRemove} className="shrink-0 rounded-lg px-2 py-2 text-xs text-muted hover:bg-danger/10 hover:text-danger" aria-label="حذف شرط">
            حذف
          </button>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        {meta?.fields.map((f) =>
          f === "minutes" ? (
            <label key={f} className="block min-w-0 flex-1 text-[11.5px] text-muted">
              {FIELD_FA.minutes.label}
              <select
                className={`${inputCls} mt-1`}
                value={windows.includes(minutes) ? minutes : ""}
                onChange={(e) => onChange({ ...cond, minutes: Number(e.target.value), lookback: null })}
              >
                {!windows.includes(minutes) && <option value="">{windowFa(minutes)}</option>}
                {windows.map((w) => (
                  <option key={w} value={w}>
                    {windowFa(w)} اخیر
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <NumberInput
              key={f}
              label={FIELD_FA[f].label}
              suffix={FIELD_FA[f].suffix}
              value={cond[f]}
              onChange={(v) => onChange({ ...cond, [f]: v })}
            />
          ),
        )}
      </div>
    </div>
  );
}

function ConditionList({ title, hint, conds, vocab, resolution, min, onChange }: {
  title: string;
  hint: string;
  conds: Condition[];
  vocab: Vocabulary;
  resolution: string;
  min: number;
  onChange: (c: Condition[]) => void;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-bold">{title}</h3>
        <span className="text-[11px] text-muted">{hint}</span>
      </div>
      <div className="space-y-2">
        {conds.map((c, i) => (
          <ConditionRow
            key={i}
            cond={c}
            vocab={vocab}
            resolution={resolution}
            onChange={(next) => onChange(conds.map((x, j) => (j === i ? next : x)))}
            onRemove={conds.length > min ? () => onChange(conds.filter((_, j) => j !== i)) : undefined}
          />
        ))}
      </div>
      {conds.length < 5 && (
        <button
          onClick={() => onChange([...conds, { kind: "rsi_below", ...KIND_DEFAULTS.rsi_below }])}
          className="mt-2 w-full rounded-xl border border-dashed border-border py-2 text-xs text-primary hover:bg-primary-soft"
        >
          + افزودن شرط
        </button>
      )}
    </div>
  );
}

export function RuleEditor({ spec, vocab, onChange }: { spec: StrategySpec; vocab: Vocabulary; onChange: (s: StrategySpec) => void }) {
  const set = (patch: Partial<StrategySpec>) => onChange({ ...spec, ...patch });
  const markets = vocab.markets.some((m) => m.symbol === spec.symbol)
    ? vocab.markets
    : [{ symbol: spec.symbol, name_fa: spec.symbol, quote: "" }, ...vocab.markets];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <label className="block min-w-40 flex-1 text-[11.5px] text-muted">
          بازار
          <select className={`${inputCls} mt-1`} value={spec.symbol} onChange={(e) => set({ symbol: e.target.value })}>
            {markets.map((m) => (
              <option key={m.symbol} value={m.symbol}>
                {m.name_fa} ({m.symbol})
              </option>
            ))}
          </select>
        </label>
        <div className="min-w-40 flex-1 text-[11.5px] text-muted">
          کندل‌ها
          <div className="mt-1 flex flex-wrap gap-1">
            {vocab.resolutions.map((r) => (
              <button
                key={r.key}
                onClick={() => set({ resolution: r.key })}
                aria-pressed={spec.resolution === r.key}
                className={`rounded-lg px-2.5 py-2 text-xs ${spec.resolution === r.key ? "bg-primary text-white" : "bg-surface-2 text-text hover:bg-primary-soft"}`}
              >
                {r.title_fa}
              </button>
            ))}
          </div>
        </div>
      </div>

      <ConditionList
        title="۱. کِی بخرد؟"
        hint="همهٔ شرط‌ها باید با هم برقرار باشند"
        conds={spec.entry}
        vocab={vocab}
        resolution={spec.resolution}
        min={1}
        onChange={(entry) => set({ entry })}
      />

      <div>
        <h3 className="mb-1.5 text-sm font-bold">۲. با چقدر پول و کِی بفروشد؟</h3>
        <div className="flex flex-wrap gap-2 rounded-xl border border-border bg-surface-2 p-3">
          <NumberInput label="اندازهٔ هر خرید" suffix="٪ سرمایه" value={spec.position_size_pct} onChange={(v) => set({ position_size_pct: v ?? 0 })} />
          <NumberInput label="هدف سود (تارگت)" suffix="٪" allowEmpty value={spec.take_profit_pct} onChange={(v) => set({ take_profit_pct: v })} />
          <NumberInput label="حد ضرر" suffix="٪" allowEmpty value={spec.stop_loss_pct} onChange={(v) => set({ stop_loss_pct: v })} />
          <NumberInput label="مکث بعد از فروش" suffix="کندل" value={spec.cooldown_candles} onChange={(v) => set({ cooldown_candles: Math.round(v ?? 0) })} />
        </div>
      </div>

      <ConditionList
        title="۳. شرط فروش اضافه (اختیاری)"
        hint="هر کدام برقرار شود، همه را می‌فروشد"
        conds={spec.exit}
        vocab={vocab}
        resolution={spec.resolution}
        min={0}
        onChange={(exit) => set({ exit })}
      />
    </div>
  );
}
