// 画面〜API〜計算エンジンを通して確かめるテスト(e2e/)。npm run e2e で動かす。
//
// - API サーバー(:8000)と画面(:3000)は、このテストが起動する。すでに起動していれば、それを使う
// - 画面は本番ビルド(next start)で動かす。先に npm run build しておく
// - データは架空データ(DEMO)だけを使う(APIキー不要。CI でも同じ結果になる)
// - ブラウザは Chromium。CI では npx playwright install --with-deps chromium で入れる。
//   別の場所にある Chromium を使うときは PW_CHROMIUM_PATH にそのパスを入れる

import { defineConfig, devices } from "@playwright/test";

const executablePath = process.env.PW_CHROMIUM_PATH || undefined;

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    locale: "ja-JP",
    timezoneId: "Asia/Tokyo",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 } },
      grepInvert: /@mobile/,
    },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: [
    {
      // .env を読まないように、APIキーの環境変数を空にして架空データだけで動かす
      command: "uv run uvicorn backend.main:create_app --factory --port 8000",
      cwd: "..",
      url: "http://localhost:8000/api/health",
      env: { JQUANTS_API_KEY: "", BACKTEST_DATA_DIR: "data/e2e" },
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: "npm run start -- -p 3000",
      url: "http://localhost:3000",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
