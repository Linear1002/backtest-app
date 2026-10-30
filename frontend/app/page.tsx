import { BacktestApp } from "@/components/BacktestApp.tsx";

// <header>・手順の <nav>・<main> は BacktestApp の中で並べる(ランドマークを入れ子にしないため)
export default function Home() {
  return <BacktestApp />;
}
