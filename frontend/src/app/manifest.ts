import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "زیرک — Zirak",
    short_name: "زیرک",
    description: "معامله‌گر هوشمند و توضیح‌پذیر با مدیریت ریسک — ساخته‌شده برای هکاتون والکس",
    start_url: "/",
    display: "standalone",
    dir: "rtl",
    lang: "fa",
    background_color: "#0c1412",
    theme_color: "#0e7c6b",
    icons: [
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
      { src: "/icon-maskable.svg", sizes: "any", type: "image/svg+xml", purpose: "maskable" },
    ],
  };
}
