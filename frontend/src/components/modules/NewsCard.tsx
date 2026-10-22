"use client";

import { useEffect, useState } from "react";
import { Badge, Card, ErrorBox, Skeleton } from "@/components/ui";
import { faNum } from "@/lib/fa";
import { modulesApi, type News } from "@/lib/modules";

const toneOf = (label: string) => (label === "مثبت" ? "up" : label === "منفی" ? "down" : "muted");

export function NewsCard({ asset }: { asset?: string }) {
  const [n, setN] = useState<News | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    modulesApi
      .news(asset)
      .then((x) => alive && setN(x))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [asset]);

  return (
    <Card title="اخبار و حال‌وهوای بازار" action={n && <Badge tone={toneOf(n.label_fa)}>{n.label_fa}</Badge>}>
      <ErrorBox message={error} />
      {!n && !error && <Skeleton className="h-24" />}
      {n && (
        <div className="space-y-3 text-sm leading-7">
          {n.source === "mock" && <p className="text-xs text-accent">تیترهای نمونه (حالت آفلاین)؛ برای خبر واقعی NEWS_SOURCE=rss را تنظیم کنید.</p>}
          <p>{n.summary_fa}</p>
          <ul className="space-y-1.5">
            {n.items.slice(0, 6).map((it, i) => (
              <li key={i} className="flex items-start gap-2 text-xs">
                <span className={`mt-1 size-2 shrink-0 rounded-full ${it.score > 0 ? "bg-up" : it.score < 0 ? "bg-down" : "bg-muted"}`} />
                {it.url ? (
                  <a href={it.url} target="_blank" rel="noreferrer" className="hover:underline" dir="auto">
                    {it.title}
                  </a>
                ) : (
                  <span dir="auto">{it.title}</span>
                )}
              </li>
            ))}
          </ul>
          {n.size_factor < 1 && (
            <p className="text-xs text-muted">
              با این خبرها، اگر «اثر خبر بر ریسک» روشن باشد، حجم خریدهای جدید به {faNum(n.size_factor * 100, 0)}٪ کاهش می‌یابد
              {n.news_risk_enabled ? "." : " (اکنون خاموش است)."}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
