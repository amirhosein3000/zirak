"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, type Health } from "@/lib/api";
import { Logo } from "./Logo";

const NAV = [
  { href: "/", label: "بازار", icon: "M3 17l6-6 4 4 8-8M14 7h7v7" },
  { href: "/build", label: "استراتژی", icon: "M4 6h16M4 12h10M4 18h7" },
  { href: "/backtest", label: "بک‌تست", icon: "M4 19V5M4 19h16M8 15l3-4 3 2 4-6" },
  { href: "/dashboard", label: "داشبورد", icon: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .health()
        .then((h) => alive && (setHealth(h), setOffline(false)))
        .catch(() => alive && setOffline(true));
    load();
    const t = setInterval(load, 10000);
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <div className="mx-auto flex min-h-dvh max-w-xl flex-col">
      <header className="sticky top-0 z-20 border-b border-border bg-bg/90 px-4 pb-2 pt-3 backdrop-blur">
        <div className="flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">
            <Logo className="size-8" />
            <div className="leading-tight">
              <div className="text-lg font-bold">زیرک</div>
              <div className="text-[11px] text-muted">معامله‌گر هوشمند و توضیح‌پذیر</div>
            </div>
          </Link>
          <div className="flex flex-col items-end gap-1">
            {offline ? (
              <span className="rounded-full bg-danger/15 px-2.5 py-0.5 text-xs font-bold text-danger">سرور در دسترس نیست</span>
            ) : health?.live_trading ? (
              <span className="rounded-full bg-danger px-2.5 py-0.5 text-xs font-bold text-white">معاملهٔ واقعی</span>
            ) : (
              <span className="rounded-full bg-primary-soft px-2.5 py-0.5 text-xs font-bold text-primary">حالت کاغذی (بدون پول واقعی)</span>
            )}
            {health?.kill_engaged && <span className="text-[11px] font-bold text-danger">کلید توقف فعال است</span>}
          </div>
        </div>
        <p className="mt-2 rounded-lg bg-accent/10 px-3 py-1.5 text-[11.5px] leading-5 text-text/80">
          ⚠️ این ابزار آموزشی و آزمایشی است و <b>توصیهٔ مالی نیست</b>. تصمیم و مسئولیت هر معامله با خود شماست.
          {health?.data === "synthetic" && <> داده‌ها فعلاً <b>شبیه‌سازی‌شده</b> هستند.</>}
          {health?.data === "live" && <> قیمت‌ها <b>زنده</b> از والکس خوانده می‌شوند؛ معاملات همچنان کاغذی است.</>}
        </p>
      </header>

      <main className="flex-1 space-y-4 px-4 pb-28 pt-4">{children}</main>

      <footer className="px-4 pb-24 text-center text-[11px] text-muted">ساخته‌شده برای هکاتون والکس · محصول مستقل، غیررسمی</footer>

      <nav className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface/95 backdrop-blur" aria-label="ناوبری اصلی">
        <ul className="mx-auto grid max-w-xl grid-cols-4">
          {NAV.map((item) => {
            const active = item.href === "/" ? path === "/" : path.startsWith(item.href);
            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className={`flex flex-col items-center gap-1 py-2.5 text-xs font-bold ${active ? "text-primary" : "text-muted"}`}
                  aria-current={active ? "page" : undefined}
                >
                  <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <path d={item.icon} />
                  </svg>
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
