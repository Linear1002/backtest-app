import type { Metadata, Viewport } from "next";
import "@fontsource/biz-udpgothic/400.css";
import "@fontsource/biz-udpgothic/700.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "日本語バックテスト",
  description: "銘柄と売買ルールを選んで、過去の株価でどうなったかを確かめるWebアプリ",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f3f5f2" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1217" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ja">
      <body className="antialiased">{children}</body>
    </html>
  );
}
