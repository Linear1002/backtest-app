import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "日本語バックテストアプリ",
  description: "投資手法・条件・銘柄を選んでバックテストを実行できるWebアプリ",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
