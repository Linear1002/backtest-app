# C++ 版エンジンの入出力の約束

C++ 版エンジンは、リファレンス実装(`engine/reference/`)と**同じ入力を受け取り、同じ形で結果を出す**。
そうすれば、正解データ(`tests/golden/`)とファイル同士で答え合わせができる。計算の中身は `docs/mvp.md` が正。

## コマンドの形

```bash
build/engine/cpp/backtest_cli 入力フォルダ 出力フォルダ
```

- 入力フォルダには `bars.csv` と `params.txt` がある
- 出力フォルダがなければ作る。中身は下の「出力」のファイル
- 終了コード
  - `0`:計算できた
  - `2`:入力(パラメータ・期間)の誤りか、データの異常で計算しなかった。このときは `error.txt` だけを書く
  - それ以外:想定していない失敗(バグ)

リファレンス実装も同じ形で動かせる:`uv run python -m engine.reference.cli 入力フォルダ 出力フォルダ`。

## 入力

### bars.csv(日足。古い順)

```
date,open,high,low,close,volume,adj_factor,ex_rt
2025-01-06,100.0,100.0,100.0,100.0,1000.0,1.0,
2025-01-07,,,,,,0.5,1
```

| 列 | 型 | 内容 |
|---|---|---|
| `date` | 文字列 `YYYY-MM-DD` | 営業日。文字列のまま比べても日付の順になる |
| `open` `high` `low` `close` | 小数(空欄あり) | 未調整の四本値。売買不成立の日は空欄 |
| `volume` | 小数(空欄あり) | 出来高(計算には使わない) |
| `adj_factor` | 小数 | 調整係数。権利落ち日以外は 1 |
| `ex_rt` | 整数(空欄あり) | 権利落ちの種類。1 分割・2 併合・3 株主割当増資。該当なしは空欄 |

- 1行目は見出し。空欄は Null
- **入力は切り出されているとは限らない**。API は銘柄の全期間を渡すので、ウォームアップより前のデータや、
  終了日より後のデータも入っている(ケース `u01`・`u02`・`h19`)。C++ 側で「読み込む範囲」
  (ウォームアップの最も古い有効日〜終了日。`docs/mvp.md` 2.2)を切り出してから計算する。
  多くのケースは、読みやすいように読み込む範囲だけを入力にしてあるが、結果はどちらでも同じになる
- 小数は `1e-10` のような指数表記のこともある。データの異常のケースでは `inf` もある。どちらも `std::stod` で読める

### params.txt(key=value)

```
start=2025-01-06
end=2025-01-15
short_window=1
long_window=2
fee_rate=0.001
slippage_rate=0.002
initial_cash=1000000.0
lot_size=100
trading_days_per_year=245
```

- 率はすべて**割合**(0.1% は `0.001`)
- `start` `end` は休場日のこともある。データの最初の日より前・最後の日より後のこともある(下の「チェックの順番」)
- `trading_days_per_year` は年率換算に使う年間の営業日数(市場ごとの設定。東証は 245)

## 出力

小数は `%.17g` で書く(`printf("%.17g", x)` または `std::setprecision(17)`)。17桁あれば、読み直したときに元の double と同じ値に戻る。
Null は空欄、真偽値は `true` / `false`。

### 表(CSV。1行目は見出し)

| ファイル | 列 | 行 |
|---|---|---|
| `daily.csv` | `date,close,short_ma,long_ma,cash,shares,valuation_price,equity` | 期間内の営業日ごと。`short_ma` `long_ma` は和 ÷ 日数(表示用)。株がない日の `valuation_price` は空欄 |
| `signals.csv` | `date,side,action` | 検出したクロスをすべて。`side` は `buy`/`sell`、`action` は `order`(注文にした)/`ignored`(売買ルールで見送り) |
| `fills.csv` | `date,signal_date,side,open_price,fill_price,shares,notional,fee,cash_after` | 約定 |
| `skipped_orders.csv` | `date,signal_date,open_price,fill_price,cash` | 資金不足で約定しなかった買い注文 |
| `events.csv` | `date,ex_rt,adj_factor,p,q,shares_before,shares_after,fraction_shares,fraction_cash,closed_position` | 株を持っている日の分割・併合の処理 |
| `trades.csv` | `entry_date,entry_price,entry_shares,buy_cost,exit_date,exit_price,exit_shares,sell_proceeds,fraction_cash,pnl,closed_by` | 買い→売りの1往復。**期間の最後まで持っていた取引も最後の行に入れる**(`exit_date` 以降は空欄、`fraction_cash` だけ入る)。併合で0株になって決済したときは `exit_price` `exit_shares` `sell_proceeds` が空欄で、`closed_by` が `merger` |

### key=value のファイル

`warmup.txt`

```
first_date=2024-11-01
last_date=2024-12-06
valid_days=25
sufficient=true
signals_unavailable_until=
```

`metrics.txt`

```
total_return=0.790750434
annualized_return=0.136188630554
max_drawdown=0.2222113421
sharpe_ratio=0.78033784
win_rate=0.4
trade_count=25
winning_trades=10
return_count=1118
```

算出不可(`annualized_return` の桁あふれ、`sharpe_ratio` の標準偏差0)と、決済した取引がないときの `win_rate` は空欄。

### error.txt(終了コード2のとき)

```
kind=data
message=調整係数 750.3 を分数に戻せませんでした(想定外の係数です)
```

`kind` は `input`(パラメータ・期間の誤り)か `data`(データの異常。`docs/mvp.md` 3.7)。答え合わせで比べるのは `kind` だけで、`message` は自由。

### チェックの順番(リファレンス実装 `run_backtest` と同じ)

誤りが2つ以上あるときに `kind` がそろうように、この順番で確かめて、最初に見つかった誤りで止める。

1. パラメータ(`input`):日数(1以上の整数・1000以下・短期 < 長期)、率(0以上・10%未満)、初期資金(1円以上・10億円以下)、
   売買単位と年間の営業日数(1以上の整数)。ケース `e03`・`e16`・`e17`・`e18`
2. 開始日 ≤ 終了日(`input`)。`e15`
3. 日付が古い順で重複がないか(`data`)。**入力全体**で確かめる(読み込む範囲を切り出すのに必要なため)。`e06`・`e07`・`e19`
4. 期間内の営業日が3日以上か(`input`)。`e02`
5. 読み込む範囲のレコード(`data`。3.7):始値と終値の片方だけ Null、0 以下・有限でない価格、調整係数の Null・0 以下・有限でない値、
   係数が1でないのに ExRT が 1〜3 以外、分割・併合の係数が 0.001〜1000 の外、p/q に戻せない係数。
   **読み込む範囲の外のレコードは確かめない**(`u01`)。`e01`・`e04`・`e05`・`e08`〜`e13`
6. 計算の途中:株数が int64 に収まらない(`data`)。`e14`

**データの範囲のチェック**(開始日がデータの最初の日より前、終了日が最後の日より後)は API の担当で、エンジンはしない。
エンジンには銘柄本来のデータの範囲が分からないため(切り出された入力では、もとの範囲を知りようがない)。
終了日がデータの最後の日より後でも、エンジンはあるデータだけで計算する(`h19`)。

## 答え合わせの基準(`docs/mvp.md` 6章)

`engine/reference/compare.py` が比べる。

- **完全に一致**:日付、`side`・`action`・`closed_by`、株数(`shares` など)、`p`・`q`、`ex_rt`、`closed_position`、
  ウォームアップのすべて、取引回数・勝った取引の数・`return_count`・勝率
- **許容誤差内**:それ以外の小数。`|C++ − Python| ≤ 1e-12 + 1e-9 × |Python|`
- 行の数が違うときは、その時点で違いとして報告する
- 出力のファイルは、比べる項目を絞っていても**全部**書く(行がなければ見出しだけ)。足りないと「ファイルがありません」と報告される
- `BACKTEST_CPP_STRICT=1` を付けると、小数も許容誤差なしで比べる。仕様どおりの順番で計算していれば、ここまで一致する

```bash
make cpp-case CASE=h01_round_trip      # 1ケースだけ動かして比べる
make test-cpp                          # engine/cpp/MILESTONE のマイルストーンまで(ファイルがなければすべて)
make test-cpp UPTO=M3                  # M3 までに合格するはずのケース・項目だけ
BACKTEST_CPP_ONLY=signals.date,signals.side make test-cpp   # 比べる項目を自分で絞る
BACKTEST_CPP_STRICT=1 make test-cpp    # ビット単位で一致するか
```

ケースの一覧と、どのマイルストーンで合格するかは `tests/golden/manifest.json`(`milestone`・`stage`・`expected_error`)。

## pybind11 から呼ぶとき(段階が進んだら)

画面から C++ 版を選べるようにするため、Python から呼べるモジュール `backtest_cpp` を作る(`engine/bindings/`)。
API 側の受け口(`backend/engines.py`)はもうできていて、次の関数を呼ぶ。

```python
backtest_cpp.run_ma_cross(
    bars,    # [(date, open, high, low, close, volume, adj_factor, ex_rt), ...]  Null は None。銘柄の全期間
    start,   # "YYYY-MM-DD"
    end,     # "YYYY-MM-DD"
    params,  # {"short_window": 5, "long_window": 25, "fee_rate": 0.001, "slippage_rate": 0.0005,
             #  "initial_cash": 1000000.0, "lot_size": 100, "trading_days_per_year": 245}
) -> dict
```

返す dict の形は `engine/reference/contract.py` の `to_contract_dict` と同じ(キーは上の CSV のファイル名、
中身は列名をキーにした dict の list。`warmup` と `metrics` は dict)。日付は文字列、Null は `None`。
入力の誤りは `backtest_cpp.InputError`、データの異常は `backtest_cpp.DataError` として投げる(どちらも `ValueError` の子クラス。メッセージは日本語)。API 側はこれをリファレンスの `EngineInputError` / `EngineDataError` に読み替える。
