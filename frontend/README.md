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
| `components/BacktestApp.tsx` | 手順(銘柄 → 戦略 → 条件 → 確認 → 結果)の画面を並べ、API を呼ぶ |
| `lib/flow.ts` | 手順の状態と移り変わり(reducer)。古い応答を捨てる・条件を変えたら前の結果に戻れない、などの決まり |
| `components/steps/` | 手順1〜4の画面 |
| `components/results/` | 結果の画面(計算書・成績表・チャート・取引の記録・注意) |
| `lib/api.ts` | API の型と呼び出し |
| `lib/format.ts` | 円・%・日付の表示 |
| `lib/chart.ts` | チャートの目盛り・座標・線のパス |
| `lib/form.ts` | 条件の入力チェック(範囲は API の ParamSpec から読む。メッセージは docs/mvp.md 4.3・API と同じ) |
| `lib/testing.ts` | テスト用の小さなデータ(アプリからは使わない) |

## 状態の決まり(lib/flow.ts)

画面の状態は React の部品の中ではなく、`lib/flow.ts` の reducer(「いまの状態」と「起きたこと」から次の状態を返す純粋な関数)にまとめている。
画面を開かなくても `npm test` で確かめられるようにするため(`lib/flow.test.ts`)。

- **古い応答は捨てる**:銘柄の詳細・バックテストの実行には番号を付け、いちばん新しい番号の応答だけを受け取る(A を押してすぐ B を押したとき、遅れて届いた A の詳細で B の条件を上書きしない)
- **結果は、その結果を出した条件でだけ見られる**:条件を変えたら手順5には移れない(元の条件に戻せば、また見られる)
- **実行中は手順を移れない**
- **手順が変わったら見出しへ、入力に誤りがあれば最初の誤りの欄へフォーカスを移す**(読み上げ・キーボード操作のため)
- **同じ銘柄を選び直しても何も消さない**。別の銘柄にしたら、日数・費用・初期資金は残し、期間だけを新しい銘柄のデータの範囲にする
