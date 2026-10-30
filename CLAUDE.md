# プロジェクト概要
日本語UIのバックテストWebアプリ。ユーザーが投資手法・条件・銘柄を選んでバックテストを実行できる。
計算はGPU(CUDA)で大量・高速に行えることが強みで、GPUがない環境ではCPUで同じ計算ができる。
最終目標:ポートフォリオ作品 → 将来的に月額サブスク。

# 開発者について
- 開発者は大学1年生。C++/CUDAは学習中。
- このプロジェクトは学習とポートフォリオが目的。開発者が面接で全コードを説明できる状態を保つこと。

# 役割分担(最重要)
- 【開発者が自分で書く】バックテスト計算コア(engine/cpp, engine/cuda)、CUDAカーネル、性能計測
  → この領域では完成コードを出さない。方針・ヒント・レビューのみ。開発者が求めた場合のみコード例を出す。
- 【Claudeが書いてよい】フロントエンド全般(UI・デザインはClaudeに一任)、API、認証、インフラ、
  Pythonリファレンス実装、テストの雛形、ビルド設定、ドキュメント
- どちらか曖昧なときは、書く前に確認する。

# 対象市場
- 最終目標:日本の証券口座から取引できる株式すべて(日本株、米国株、その他外国株)。
- MVPは東証上場株・日足のみ。ただし最初から複数市場に拡張できる設計にする:
  - 銘柄は「市場+コード」で一意に識別する(例: TSE:7203, NASDAQ:AAPL)
  - 通貨、取引カレンダー(休場日)、売買単位(日本株は原則100株)、値幅制限を市場ごとの設定として持つ
  - 株式分割・配当の調整方法を明示する

# MVP仕様
- MVPの範囲・戦略・指標の定義は docs/mvp.md を正とする。

# バックテストの正しさ(絶対ルール)
- 先読みバイアス禁止:時点tの判断に、t以降のデータを使わない。シグナルは原則「当日終値で判定→翌日始値で約定」。
- 生存者バイアスに注意:上場廃止銘柄の扱いを明示する。
- 手数料・スリッページを必ずパラメータとして持つ(デフォルト0にしない)。
- 正しさの基準は3段階:
  1. Pythonリファレンス実装(遅くてよい、読んで正しいとわかるコード)が正
  2. C++ CPU版はリファレンスと一致すること
  3. CUDA版はC++ CPU版と一致すること(浮動小数点の許容誤差をテストで明示)

# 技術スタック
- フロントエンド:Next.js + TypeScript + Tailwind CSS(UI文言はすべて日本語)
- APIサーバー:Python + FastAPI
- 計算エンジン:C++17(CPU版)、CUDA C++(GPU版)、pybind11でPythonから呼び出す
- ビルド:CMake
- テスト:pytest(Python・結果一致テスト)、GoogleTest(C++単体)
- データ保存:Parquet
- 開発環境:Windows + WSL2 Ubuntu、GPUはRTX 3060(VRAM 12GB)、CUDA Toolkit 13.2

# ディレクトリ構成
- frontend/         Next.js
- backend/          FastAPI
- engine/reference/ Pythonリファレンス実装
- engine/cpp/       C++ CPU版エンジン
- engine/cuda/      CUDAカーネル
- engine/bindings/  pybind11
- tests/            一致テスト・結合テスト
- data/             株価データ(Git管理しない)
- docs/             設計メモ・仕様

# 作業の進め方
- 実装前に計画を出し、承認を得てから書く。
- 1つの変更は小さく。1機能=1ブランチ。
- 計算ロジックを変更したら必ずテストを追加・実行し、結果を報告する。
- 推測で書かない。ライブラリのAPIは最新ドキュメントで確認する。
- 株価データの取得元は利用規約を確認し、再配布禁止のデータをリポジトリやアプリ経由で配布しない。

# 秘密情報
- APIキー(JQUANTS_API_KEY など)は `.env` に置く。`.env` はコミットしない。Claude は `.env` を作らない・読まない。
- APIキーを画面やログに出さない・コミットしない。例外メッセージやデバッグ出力にも含めない。
- 必要な環境変数は `.env.example` に名前だけ書く(値は空)。

# 言語
- UIの文言・エラーメッセージ:日本語
- 変数名・関数名:英語
- コメント・コミットメッセージ:日本語でOK

# コマンド
リポジトリ直下で実行する。前提ツール:build-essential、cmake 3.28 以上、ninja-build、uv、fnm。

| コマンド | 内容 |
|---|---|
| `make setup` | 依存のインストール(uv sync / npm ci)と CMake の設定。最初と、依存が変わったときに実行 |
| `make test` | C++ のビルド → pytest → ctest(GoogleTest)→ 画面の関数のテスト(`npm test`) |
| `make lint` | ruff check / ruff format --check / ESLint |
| `make dev-api` | API サーバー起動 → http://localhost:8000/api/health 、API ドキュメント http://localhost:8000/docs |
| `make dev-web` | 画面の開発サーバー起動 → http://localhost:3000 |
| `make data-symbols` | J-Quants の銘柄一覧を取得して保存(APIキーが必要。docs/data.md) |
| `make data-fetch SYMBOLS="TSE:7203"` | J-Quants の日足を取得して保存 |
| `make data-info SYMBOL=DEMO:1003` | 保存済みデータの期間・権利落ちを表示 |
| `make data-check` | docs/mvp.md 3.1 の「要確認」を実データで調べる(APIキーが必要。10分ほど) |
| `make test-cpp` | C++ 版エンジンを正解データ(tests/golden)と答え合わせ。`engine/cpp/MILESTONE` のマイルストーンまで(`UPTO=M3` で指定も可) |
| `make cpp-case CASE=h01_round_trip` | 1ケースだけ C++ 版で動かして比べる |
| `make golden` | 正解データをリファレンス実装で作り直す(リファレンスや仕様を直したとき。差分を確かめてからコミット) |

- Python:バージョンは `.python-version`(3.14)。依存の追加は `uv add <pkg>`(開発用は `uv add --dev <pkg>`)、実行は `uv run <cmd>`
- Node.js:バージョンは `.nvmrc`(24 LTS)。fnm で管理(`fnm use`)。依存の追加は `npm install <pkg> --prefix frontend`
- C++:ビルドディレクトリは `build/`(Ninja)。既定は Release。デバッグ用は `cmake -S . -B build-debug -G Ninja -DCMAKE_BUILD_TYPE=Debug`。CUDA を有効にするときは `cmake -S . -B build -G Ninja -DBACKTEST_ENABLE_CUDA=ON`
- clangd は `build/compile_commands.json` を読む(`make setup` で生成される)
- C++ 版エンジン(開発者が書く):手順は docs/cpp/README.md(マイルストーン M0〜M8)、入出力は docs/cpp/contract.md。
  開発者に頼まれたら cpp-tutor サブエージェントでヒント・説明・レビューをする(答えのコードは書かない)
