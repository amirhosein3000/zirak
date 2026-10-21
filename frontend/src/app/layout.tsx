import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@fontsource/vazirmatn/400.css";
import "@fontsource/vazirmatn/500.css";
import "@fontsource/vazirmatn/700.css";
import "./globals.css";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "زیرک | Zirak",
  description: "زیرک — معامله‌گر هوشمندی که دلیل هر کارش را می‌گوید. تحلیل بازار، ساخت استراتژی با زبان فارسی، بک‌تست و معاملهٔ کاغذی.",
  applicationName: "Zirak",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0e7c6b" },
    { media: "(prefers-color-scheme: dark)", color: "#0c1412" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fa" dir="rtl" className="h-full antialiased">
      <body className="min-h-full">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
