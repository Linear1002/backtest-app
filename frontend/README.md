# frontend

Next.js(TypeScript・Tailwind CSS・App Router)の画面。起動方法などはリポジトリ直下の `CLAUDE.md` の「コマンド」欄と `Makefile` を参照。

- 開発サーバー:リポジトリ直下で `make dev-api`(API)と `make dev-web`(画面)→ http://localhost:3000
- 画面からの `/api/...` は `next.config.ts` の rewrites で FastAPI(既定は http://localhost:8000、環境変数 `BACKEND_URL` で変更可)に転送する
- テスト:`npm test`(`lib/` の計算・表示の関数。Node.js の test runner で TypeScript をそのまま動かす)
- デザインの決まりごと:`DESIGN.md`
- `AGENTS.md` は `next dev` が自動で書き戻すファイルなので、消さずにコミットしておく

## ファイルの構成

| 場所 | 中身 |
|---|---|
| `app/` | レイアウト・トップページ・色や文字の設定(`globals.css`) |
| `components/BacktestApp.tsx` | 手順(銘柄 → 戦略 → 条件 → 確認 → 結果)の状態をまとめる |
| `components/steps/` | 手順1〜4の画面 |
| `components/results/` | 結果の画面(計算書・成績表・チャート・取引の記録・注意) |
| `lib/api.ts` | API の型と呼び出し |
| `lib/format.ts` | 円・%・日付の表示 |
| `lib/chart.ts` | チャートの目盛り・座標・線のパス |
| `lib/form.ts` | 条件の入力チェック(docs/mvp.md 4.3 と同じメッセージ) |
