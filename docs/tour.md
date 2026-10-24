# コードの読み方ガイド

このリポジトリを初めて読む人(未来の自分を含む)のための地図。
1回のバックテストが「画面のボタン → API → 計算エンジン → 画面の結果」と、どのファイルのどの関数を通るかを順に追う。
面接で「全体の流れを説明してください」と言われたときの下書きにもなる(`docs/interview.md`)。

- 計算の決まりごとの正:`docs/mvp.md`(このガイドでは「仕様 2.6」のように節番号で書く)
- C++ 版を自分で書く道のり:`docs/cpp/README.md`

## 0. 全体の地図

```mermaid
flowchart LR
  subgraph 画面["画面(frontend/ Next.js)"]
    A["BacktestApp.tsx<br/>手順の画面を並べる"] --> F["lib/flow.ts<br/>状態と決まり"]
    A --> C["lib/api.ts<br/>API の呼び出し"]
    R["results/ResultView.tsx<br/>結果の画面"]
  end
  C -- "/api/... (rewrites で転送)" --> RT
  subgraph API["API(backend/ FastAPI)"]
    RT["api/routes.py"] --> V["api/validation.py<br/>入力チェック 4.3"]
    RT --> S["marketdata/service.py<br/>データの窓口"]
    RT --> E["engines.py<br/>エンジンの切り替え"]
    RT --> CV["api/convert.py<br/>結果を JSON の形に"]
  end
  S --> DS1["synthetic.py<br/>架空データ"]
  S --> DS2["jquants.py<br/>J-Quants"]
  DS2 --> ST[("store.py<br/>Parquet")]
  E --> PY["engine/reference/<br/>Python リファレンス"]
  E -. "ビルドしたら" .-> CPP["engine/cpp/<br/>C++ 版(自分で書く)"]
  CV -- JSON --> R
```

## 1. 画面(`frontend/`)

| ファイル | 役割 | 読むときのポイント |
|---|---|---|
| `app/page.tsx` → `components/BacktestApp.tsx` | 画面の骨組み。ヘッダー・手順の表示・条件票・各手順の画面を並べ、API を呼ぶ | 状態は自分では持たず、`useReducer(flowReducer)` に任せている |
| `lib/flow.ts` | **手順の状態と、その移り変わり**(reducer) | いちばん大事な決まりはここ:古い応答を捨てる(番号)、結果は同じ条件のときだけ見られる、実行中は何も変えられない |
| `components/steps/` | 手順1〜4の画面(銘柄・戦略・条件・確認) | 画面は「見せる」と「ボタンが押されたことを伝える」だけ。判断は flow.ts |
| `lib/form.ts` | 入力欄の文字 → 数値、入力チェック | 範囲は API が返す ParamSpec から読む。メッセージは API と同じ文(仕様 4.3)。同じ表で両方を確かめている(6章) |
| `lib/api.ts` | `fetch` のラッパーと、API の型 | 失敗はすべて日本語の `ApiError` にする。「API が起動していない」と「API の中のエラー」を見分ける |
| `components/results/ResultView.tsx` | 結果の画面(計算書・成績表・取引の記録・注記) | 数字の見せ方の決まりは `DESIGN.md` |
| `components/results/TimeSeriesCharts.tsx` + `lib/chart.ts` | 株価・資産額・ドローダウンのチャート(SVG を自前で描く) | 目盛りは `niceScale`、数字の桁は `axisLabels`(`lib/format.ts`) |

**1回のバックテストで画面の中で起きること**

1. 「バックテストを実行」→ `BacktestApp.tsx` の `run()`
2. `currentRequest(state)`(flow.ts)で、いまの条件からリクエストを作る
3. `dispatch({ type: "runStarted", id, request })` → 実行中になる(手順の移動・条件の変更を受け付けなくなる)
4. `api.runBacktest(request)`(api.ts)→ `POST /api/backtests`
5. 成功:`runSucceeded` → 結果を `last` に記録して手順5へ。失敗:`runFailed` → 入力の誤りなら手順3のその欄へ、それ以外は確認の画面に文で出す

## 2. 中継(`frontend/next.config.ts`)

画面からの `/api/...` は、Next.js の rewrites で FastAPI(既定 `http://localhost:8000`)に転送する。
画面と API が同じオリジンに見えるので、CORS の設定がいらない。待ち時間の上限は `experimental.proxyTimeout`。

## 3. API(`backend/`)

| ファイル | 役割 |
|---|---|
| `main.py` | `create_app()`:アプリを作る。`uvicorn --factory` で呼ぶので、import しただけでは .env を読まない |
| `api/routes.py` | エンドポイント:`/api/meta`・`/api/symbols`・`/api/symbols/{symbol_id}`・`/api/strategies`・`/api/backtests` |
| `api/validation.py` | 入力チェック(仕様 4.3)。`check_param` が ParamSpec(種類・範囲)から判定する |
| `api/errors.py` | 例外 → 日本語の JSON(`{"detail": ..., "errors": [...]}`)。想定外の例外も必ず JSON にし、中身はログにだけ出す |
| `api/convert.py` | エンジンの結果 → 画面に返す形。注記(清算コスト控除前・生存者バイアスなど)もここで作る |
| `engines.py` | 計算エンジンの切り替え(Python リファレンス / C++ 版)。C++ 版がビルドされていれば自動で選べるようになる |
| `strategies.py` | 戦略の一覧と、パラメータの既定値・範囲・説明(ParamSpec。画面の入力欄もこれから作る) |

**`POST /api/backtests` の中(`run_backtest_endpoint`)**

1. 戦略が使えるか → 銘柄IDを読む(`SymbolId.parse`。市場ごとの設定もここで決まる)→ パラメータのチェック(`validate_params`。% → 割合に直す)→ エンジンを選ぶ(`get_engine`)
2. 銘柄が対象か(`require_listed`。現在上場の銘柄だけ:仕様 3.6)→ 日足を読む(`service.load`)
3. 期間のチェック(`validate_period`。データの範囲のチェックはここだけで行う)
4. **銘柄の全期間の日足**をエンジンに渡す(`convert.to_engine_bars` → `run(...)`)。読み込む範囲の切り出しはエンジンの仕事
5. 結果を `convert.*_out` で JSON の形にして返す(計算にかかった時間も測る)

## 4. 株価データ(`backend/marketdata/`)

| ファイル | 役割 |
|---|---|
| `source.py` | データソースの約束(`DataSource` の Protocol):銘柄一覧・日足・データの範囲 |
| `synthetic.py` | 架空データ(DEMO)。12銘柄に、分割・併合・増資・売買停止・途中上場などの境界ケースを仕込んである。APIキーなしで動く |
| `jquants.py` | J-Quants API V2 のクライアント。1分間の回数の上限(`RateLimiter`)、429 のときの待ち、ページ送り |
| `store.py` | Parquet への保存と読み込み(書き込みは一時ファイル → 置き換えで、途中で壊れないようにする) |
| `service.py` | API から見た窓口。銘柄IDからデータソースを選び、保存が古ければ取り直す |
| `models.py` | 銘柄ID(`TSE:7203` のような「市場:コード」)、日足、市場ごとの設定(売買単位・年間の営業日数など) |

利用規約(私的使用のみ)のため、取得したデータは `data/` に置き、Git には入れない(`docs/data.md`)。

## 5. 計算エンジン(`engine/reference/`)

Python で書いた「正解」。遅くてよいので、仕様の文と1対1で読めるように書いてある。C++ 版はこれと一致させる。

| ファイル | 中身 | 仕様 |
|---|---|---|
| `backtest.py` の `run_backtest` | 全体の流れ(下の表) | 2章・5章 |
| `indicators.py` | 時点 t 基準の調整(CumAdj)、移動平均の和、D(t)、クロスの判定 | 2.2・2.3 |
| `ratio.py` | 調整係数 → 分数 p/q(`floor(x + 0.5)` で丸める) | 2.8 |
| `metrics.py` | 総リターン・年率・最大ドローダウン・シャープレシオ・勝率 | 5章 |
| `types.py` | 日足・パラメータ・結果の型 | − |
| `contract.py`・`csvio.py`・`compare.py`・`cli.py` | C++ 版との答え合わせ(ファイルの形・比べ方・コマンド) | 6章・`docs/cpp/contract.md` |

**`run_backtest` の流れ**

| 順番 | 関数・処理 | 仕様 |
|---|---|---|
| 1 | `validate_params`(パラメータ)→ 開始日 ≤ 終了日 → `validate_order`(日付の順番。入力全体) | 4.3・3.7 |
| 2 | `select_load_range`:開始日より前の有効日を `long_window` 個まで + 期間。期間の営業日が3日未満ならエラー | 2.2・4.3 |
| 3 | `validate_records`:読み込む範囲のレコードだけをチェック | 3.7 |
| 4 | `compute_cross_states`:有効日ごとに D(t) を計算 | 2.2・2.3 |
| 5 | 期間の営業日ごとに:**分割・併合 → 約定 → 評価 → シグナル**の順 | 2.5 |
| 6 | `compute_metrics`、ウォームアップの情報 | 5章・4.1 |

## 6. テスト

| 場所 | 何を確かめるか | 動かし方 |
|---|---|---|
| `tests/python/test_reference_*.py` | エンジンの手計算のケース、性質のテスト(未来のデータを書き換えても過去のシグナルが変わらない、など) | `uv run pytest` |
| `tests/python/test_api.py` ほか | API・入力チェック・データ層・設定 | 同上 |
| `tests/fixtures/` + `test_param_contract.py` | 画面と API で共有する表:パラメータの定義(`ma_cross_params.json`)と、入力 → メッセージ(`param_messages.json`)。画面のテスト(`lib/form.test.ts`)も同じ表を読むので、片方だけ変えるとどちらかが落ちる | 同上 |
| `tests/golden/` + `test_golden.py` | 正解データ(60ケース)。リファレンスがビット単位で再現すること(`make test` の pytest で動く)、C++ 版があれば一致すること(`make test-cpp`) | `make test`・`make test-cpp` |
| `tests/cpp/` | C++ のビルド確認(C++ 版のテストは `engine/cpp/tests/` に自分で書く) | `ctest --test-dir build` |
| `frontend/lib/*.test.ts` | 画面の状態遷移・入力チェック・目盛り・表示 | `npm --prefix frontend test` |
| `frontend/e2e/` | 画面〜API〜エンジンを通しで(架空データ)。各手順でアクセシビリティの自動チェック | `make e2e` |
| `.github/workflows/ci.yml` | 上の全部を、push と PR のたびに GitHub で | 自動 |

## 7. おすすめの読む順番

1. `docs/mvp.md` の 2章(戦略)と 5章(指標)を読む
2. `engine/reference/indicators.py` → `backtest.py` の `run_backtest`(仕様の節番号を見ながら)
3. `tests/golden/cases/h01_round_trip/` の入力と正解を開き、手で1日ずつ追ってみる
4. `backend/api/routes.py` の `run_backtest_endpoint` → `api/convert.py`
5. `frontend/lib/flow.ts` と `flow.test.ts`(テストの名前を読むだけで、画面の決まりが分かる)
6. `frontend/components/results/ResultView.tsx`(API の結果がどう画面になるか)

## 8. 手を動かして確かめる

- `make dev-api` → http://localhost:8000/docs で `POST /api/backtests` を「Try it out」。`DEMO:1003` の結果の `events` に分割の処理が出る
- `make dev-web` → 画面で `DEMO:1004`(1:3分割)を全期間で実行し、取引の記録の「100株 → 300株」を見つける。なぜ売値が買値より安いのに利益なのかを説明してみる
- `frontend/lib/flow.test.ts` を1つ読み、似たテストを1つ足してみる(`npm --prefix frontend test`)
- `uv run python -m engine.reference.cli tests/golden/cases/h01_round_trip/input /tmp/out` を動かして、`uv run python -m engine.reference.compare tests/golden/cases/h01_round_trip/expected /tmp/out` で正解と比べる
