"use client";

// Tiny per-browser state shared across pages (selected market, current strategy, last report).
// It's a convenience only: everything still works if storage is unavailable.

import { useCallback, useSyncExternalStore } from "react";
import type { RunRequest, StrategySpec } from "./api";

export type AppState = {
  symbol: string;
  draftText: string;
  spec: StrategySpec | null;
  run: RunRequest | null; // what the last backtest ran (used to start the paper bot)
  lastReportId: string | null;
};

const KEY = "zirak-state-v1";
const DEFAULTS: AppState = {
  symbol: "BTCTMN",
  draftText: "وقتی بیت‌کوین ۵٪ ریخت، با ۱۰٪ سرمایه بخر و با ۳٪ سود بفروش",
  spec: null,
  run: null,
  lastReportId: null,
};

let state: AppState = DEFAULTS;
let loaded = false;
const listeners = new Set<() => void>();

function load(): void {
  if (loaded || typeof window === "undefined") return;
  loaded = true;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (raw) state = { ...DEFAULTS, ...(JSON.parse(raw) as Partial<AppState>) };
  } catch {
    /* storage unavailable */
  }
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function useAppState(): [AppState, (patch: Partial<AppState>) => void] {
  const snapshot = useSyncExternalStore(
    subscribe,
    () => {
      load();
      return state;
    },
    () => DEFAULTS,
  );
  const update = useCallback((patch: Partial<AppState>) => {
    state = { ...state, ...patch };
    try {
      window.localStorage.setItem(KEY, JSON.stringify(state));
    } catch {
      /* ignore */
    }
    listeners.forEach((l) => l());
  }, []);
  return [snapshot, update];
}
