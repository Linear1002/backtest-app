# C++ 版エンジンを自分で書く

このガイドは、`engine/cpp/` に C++ 版のバックテストエンジンを**自分で**書くための道のり。
完成コードは載せていない(`CLAUDE.md` の役割分担)。代わりに、各段階で「何を作るか」「どの C++ の機能を覚えるか」「どう確かめるか」を書いてある。

- 計算の決まりごと:`docs/mvp.md`(これが正)
- 入出力の形:`docs/cpp/contract.md`
- 正解の実装:`engine/reference/`(Python。迷ったらここを読む。1つの関数が仕様の1つの節に対応している)
- 正解データ:`tests/golden/`(38ケース)。`make test-cpp` で自分の C++ 版と比べられる

## 全体の流れ

```
tests/golden/cases/h01_round_trip/input/   ─┐
   bars.csv  params.txt                      │  あなたが書く
                                             ▼
                        build/engine/cpp/backtest_cli 入力 出力
                                             │
                                             ▼
                        出力フォルダ(daily.csv, signals.csv, ... metrics.txt)
                                             │  engine/reference/compare.py が比べる
                                             ▼
tests/golden/cases/h01_round_trip/expected/ と一致すれば合格
```

| 段階 | マイルストーン | できるようになること | 確かめ方 |
|---|---|---|---|
| 準備 | M0 | `engine/cpp` をビルドできる | `backtest_cli` が使い方を表示する |
| 段階1 | M1 | 入力ファイルを読める | 自分のユニットテスト |
| | M2 | データのチェックと読み込む範囲 | エラーのケース(e02〜e04)に合格 |
| | M3 | 移動平均とクロス | シグナルの日付が段階1の全ケースで一致 |
| | M4 | 売買の流れ(分割なし) | 約定・資産額・取引が一致 |
| | M5 | 成績指標とウォームアップ | **段階1の全ケースに合格** |
| 段階2 | M6 | 分割・併合・増資 | **全38ケースに合格** |
| 仕上げ | M7 | 速さを測る | Python との速さの比較表 |
| | M8 | Python から呼べるようにする | 画面で「C++ CPU 版」を選べる |

目安:1つのマイルストーンに数日〜1週間。急がなくていい。M5 まで行けば、面接で「C++ でバックテストエンジンを書いて、Python のリファレンスとビット単位で一致させた」と言える。

## ファイルの置き方(おすすめ)

```
engine/cpp/
├── CMakeLists.txt
├── include/backtest/
│   ├── types.hpp      … Bar・Params・結果の構造体
│   ├── io.hpp         … ファイルの読み書き
│   ├── checks.hpp     … データのチェック(3.7)と p/q(2.8)
│   ├── indicators.hpp … 移動平均と D(t)
│   └── engine.hpp     … run_ma_cross(全体の流れ)
├── src/
│   ├── io.cpp, checks.cpp, indicators.cpp, engine.cpp, metrics.cpp
│   └── main.cpp       … backtest_cli(引数を読んで、io と engine を呼ぶだけ)
└── tests/
    └── *_test.cpp     … 自分で書く GoogleTest
```

`.hpp`(ヘッダー)には「こういう関数がある」という宣言を、`.cpp` には中身を書く。
こう分けると、テストからも `main.cpp` からも同じ関数を使える。

---

## M0:ビルドできる状態を作る

**作るもの**:`engine/cpp/CMakeLists.txt` と、引数を確かめるだけの `src/main.cpp`。

ルートの `CMakeLists.txt` は、`engine/cpp/CMakeLists.txt` があれば自動で読み込むようにしてある。
ビルドの設定は Claude が書いてよい範囲なので、ひな形を載せておく(中身を1行ずつ理解してから使うこと)。

M0 ではこれだけでいい:

```cmake
# engine/cpp/CMakeLists.txt(M0)
add_executable(backtest_cli src/main.cpp)
target_compile_features(backtest_cli PRIVATE cxx_std_17)
```

M1 で `.cpp` が増えてきたら、計算の部分を「ライブラリ」にまとめて、`backtest_cli` と自分のテストの両方から使う:

```cmake
# engine/cpp/CMakeLists.txt(M1 以降)
add_library(backtest_core
  src/io.cpp
  # src/checks.cpp などは、作ったら足していく
)
target_include_directories(backtest_core PUBLIC include)
target_compile_features(backtest_core PUBLIC cxx_std_17)

add_executable(backtest_cli src/main.cpp)
target_link_libraries(backtest_cli PRIVATE backtest_core)

# 自分で書くユニットテスト(make test で ctest が動かす)
add_executable(backtest_unit_tests tests/io_test.cpp)
target_link_libraries(backtest_unit_tests PRIVATE backtest_core GTest::gtest_main)
gtest_discover_tests(backtest_unit_tests)
```

- `add_library`:いくつもの `.cpp` をまとめた「部品」。`backtest_cli` とテストの両方がこれを使う
- `-ffp-contract=off` と警告(`-Wall -Wextra`)は、ルートの `CMakeLists.txt` で全体にかけてある
- `CMakeLists.txt` を書き換えると、次の `cmake --build build`(`make test` など)のときに自動で設定し直される

**覚える C++**:`int main(int argc, char* argv[])` で引数を受け取る、`return` の値が終了コードになる。

```cpp
#include <iostream>

int main(int argc, char* argv[]) {
  if (argc != 3) {
    std::cerr << "使い方: backtest_cli 入力フォルダ 出力フォルダ\n";
    return 64;  // 使い方の誤り
  }
  std::cout << "入力: " << argv[1] << "\n";
  return 0;
}
```

**確かめ方**

```bash
make test                                   # ビルドとテストが通る
./build/engine/cpp/backtest_cli             # 使い方が表示される
```

---

## M1:入力ファイルを読む

**作るもの**:`bars.csv` を `std::vector<Bar>` に、`params.txt` を `Params` に読み込む関数。

**覚える C++**

- `struct`:いくつかの値をひとまとめにする
- `std::vector<T>`:長さが変わる配列
- `std::optional<double>`:「値がないかもしれない」を表す型(売買不成立の日の価格に使う)
- `std::ifstream` と `std::getline`:ファイルを1行ずつ読む
- `std::stod` `std::stoi` `std::stoll`:文字列 → 数値(失敗すると例外を投げる)
- 例外:`throw std::runtime_error("…")` と `try { … } catch (const std::exception& e) { … }`

`std::optional` の使い方(エンジンとは関係のない例):

```cpp
#include <optional>

std::optional<double> parse_temperature(const std::string& text) {
  if (text.empty()) return std::nullopt;  // 値がない
  return std::stod(text);
}

auto t = parse_temperature("");
if (t.has_value()) { /* *t で中身を使う */ }
```

1行をカンマで区切る(これも一般的な例):

```cpp
std::vector<std::string> split(const std::string& line, char sep) {
  std::vector<std::string> fields;
  std::string field;
  std::istringstream stream(line);
  while (std::getline(stream, field, sep)) fields.push_back(field);
  if (!line.empty() && line.back() == sep) fields.push_back("");  // 最後が空欄のとき
  return fields;
}
```

**ヒント**

- `bars.csv` の1行目(見出し)が `date,open,high,low,close,volume,adj_factor,ex_rt` かどうかを確かめる
- 空欄は `std::nullopt`。`ex_rt` は `std::optional<int>`
- `params.txt` は、まず `key` → `value` の `std::map<std::string, std::string>` に入れてから、必要な型に変換すると楽
- 日付は `std::string` のまま持ってよい(`"2025-01-06" < "2025-01-07"` は文字列の比較でも正しい)
- 読む関数は `std::istream&` を受け取るようにすると、テストで `std::istringstream` を渡せる

**落とし穴**:Windows で編集したファイルは行末に `\r` が残ることがある(CRLF)。`getline` のあとで消しておく。

**確かめ方**:GoogleTest で、3行くらいの CSV を文字列で渡し、Null の日・`ex_rt` がある日を正しく読めるかを確かめる。
`cpp-tutor` に「M1 のテストで確かめるべきケースを挙げて」と聞いてもいい。

---

## M2:データのチェックと、読み込む範囲

**作るもの**(`docs/mvp.md` 3.7・2.2・2.8)

1. 日付が古い順か(入力全体)
2. 読み込む範囲の切り出し:開始日より前の有効日を `long_window` 個まで + 期間
3. 範囲内のレコードのチェック(始値・終値・調整係数・ExRT)
4. 調整係数を分数 p/q に戻す関数(`recover_split_ratio`)
5. 入力の誤り(4.3)のチェック
6. エラーのときに `error.txt` を書いて、終了コード `2` で終わる

**覚える C++**

- `const std::vector<Bar>& bars`:コピーせずに渡す(読むだけなら `const` を付ける)
- 自分の例外の型:`struct DataError : std::runtime_error { using std::runtime_error::runtime_error; };`
- `std::isfinite`、`std::floor`、`std::abs`(`<cmath>`)
- `int64_t`(`<cstdint>`):株数は必ずこの型にする(`int` は約21億までしか入らない)

**ヒント**

- p/q は「q を 1〜1000 まで回して、誤差がいちばん小さいものを残す」。誤差が同じなら先に見つかった方(q が小さい方)を残すので、比べるのは `<`(`<=` ではない)
- 丸めは `std::floor(ratio * q + 0.5)`。**`std::round` は使わない**(0.5 の扱いが Python と違う。`docs/mvp.md` 2.8)
- 相対誤差は `std::abs(p / q - ratio) / ratio`。`p / q` は整数の割り算にならないように、`static_cast<double>(p) / q` にする

**確かめ方**

```bash
uv run pytest tests/python/test_golden.py -k "cpp and e0" -v   # エラーのケースだけ
```

e02〜e04(段階1)が通れば合格。e01・e05 は段階2(係数を扱う)なので、M6 で通ればいい。

---

## M3:移動平均とクロス

**作るもの**(`docs/mvp.md` 2.2・2.3)

1. 有効日 t ごとに、CumAdj を t から過去へ掛けていき、P_t(s) = C(s) × CumAdj_t(s) を作る
2. 直近 `window` 個の有効日の P_t(s) を、**古い日から順に**足して S_window(t) にする
3. D(t) = S_short(t) × long_window − S_long(t) × short_window
4. 前の有効日 t' の D(t') と比べてクロスを判定する。D(t') は **t' の日に計算した値**を使う(t の基準で計算し直さない)

**覚える C++**:添字で回す `for` 文、`std::vector<double>`、`std::optional<double>`(D が未定義の日)。

**落とし穴**

- 和の順番を変えない。`std::accumulate` は古い順に足すので使ってもよいが、自分で `for` で書いた方が仕様との対応が分かりやすい
- `float` は使わない。すべて `double`。`long double` も使わない(Python と結果がずれる)
- コンパイラが掛け算と足し算を1つの命令(FMA)にまとめると、丸めが変わって D の符号がずれることがある。
  ルートの `CMakeLists.txt` の `-ffp-contract=off` がそれを止めている。`-ffast-math` は付けない
- 段階1のケースは調整係数がすべて1なので、CumAdj は全部1になる。でも、計算の形は段階2を見越して仕様どおりに書いておく

**確かめ方**:この段階ではまだ売買をしないので、`signals.csv` の `action` は仮に全部 `order` でいい。比べる項目を絞る。

```bash
BACKTEST_CPP_ONLY=signals.date,signals.side,daily.short_ma,daily.long_ma make test-cpp STAGE=1
```

---

## M4:売買の流れ(分割なし)

**作るもの**(`docs/mvp.md` 2.4〜2.7・2.9)。期間内の営業日ごとに、次の順で処理する。

1. (分割・併合 … M6 で作る)
2. 約定:前の有効日に出た注文があり、今日の始値があれば約定する。始値がなければ繰り越す
3. 評価:資産額 = 現金 + 株数 × 評価価格
4. シグナル判定:クロスが出たら、売買ルール(2.4)で注文にするか見送るかを決める

**覚える C++**

- `enum class Side { Buy, Sell };`:決まった選択肢を型にする
- `std::optional<Order> pending;`:「待っている注文がない」を `std::nullopt` で表す
- 状態(現金・株数・待っている注文・持っている取引)を1つの `struct` にまとめると見通しがよい

**ヒント**

- 株数の決め方(2.7)は式の順番どおりに書く。`lots` が1多くなる境目の補正も忘れない(ケース `h05_lot_correction`)
- 買い:`cash -= unit_cost * shares`。売り:`cash += notional - fee`
- `trades.csv` には、期間の最後まで持っていた取引も入れる(`docs/cpp/contract.md`)

**確かめ方**

```bash
BACKTEST_CPP_ONLY=signals,fills,skipped_orders,daily,trades make test-cpp STAGE=1
make cpp-case CASE=h01_round_trip      # 1ケースずつ。違う行が表示される
```

---

## M5:成績指標とウォームアップの情報

**作るもの**(`docs/mvp.md` 5章・4.1・6章):`metrics.txt` と `warmup.txt`。

**覚える C++**:`std::sqrt`、`std::pow`、`std::isfinite`、小数を17桁で書く方法。

```cpp
#include <cstdio>
char buffer[32];
std::snprintf(buffer, sizeof buffer, "%.17g", 0.1);  // "0.10000000000000001"
```

**ヒント**

- 年率リターンは `std::pow(growth, 245.0 / n) - 1`。結果が有限でなければ空欄(算出不可)
- シャープレシオは「平均 → 偏差の2乗の和 → `n - 1` で割って平方根 → `(平均 / 標準偏差) × √245`」の順(6章)
- 勝率は、決済した取引がなければ空欄

**確かめ方**

```bash
make test-cpp STAGE=1
```

**ここまで全部通れば、段階1の完成。** ブランチを切ってコミットし、PR を作って `code-reviewer` と `quant-validator` に見てもらおう。

---

## M6:分割・併合・増資(段階2)

**作るもの**(`docs/mvp.md` 2.8・5章・3.7)

1. 1日の処理の手順1:ExRT が1か2で調整係数が1でない日に株を持っていたら、p/q で持ち株数を変える
2. 端数 `fraction` を評価価格で現金に換える。0株になったら、その日に決済(待っている売り注文は取り消す)
3. 有効日でない日の評価価格:直前の有効日の終値 × (その翌営業日から今日までの分割・併合の係数の積)
4. 株主割当増資(ExRT=3)は持ち株数を変えない(移動平均の調整には使う。M3 で作った CumAdj がそのまま効く)

**覚える C++**:整数だけの計算と、桁あふれのチェック。

```cpp
#include <cstdint>
#include <limits>

// a × b が int64_t に収まるか(a, b は 0 以上)
bool fits(int64_t a, int64_t b) {
  return b == 0 || a <= std::numeric_limits<int64_t>::max() / b;
}
```

**ヒント**

- `new_shares = shares * p / q` と `remainder = shares * p % q` は整数で計算する(`double` を通さない)
- 端数の株数は `static_cast<double>(remainder) / q`、現金にするのは `端数 × 評価価格`(この順番)
- 落としやすいケース:`h08`(端数)、`h09`(0株になる)、`h11` と `d1008`(売買不成立の日が権利落ち日)、`h17`(D(t') の基準)

**確かめ方**

```bash
make test-cpp            # 全38ケース
```

**全部通れば、段階2の完成。** これで「仕様からエンジンを書き、独立した実装と一致させた」と言える。

---

## M7:速さを測る(性能計測は自分の担当)

- `std::chrono::steady_clock` で、計算の部分だけの時間を測る(ファイルの読み書きは含めない)
- 同じケースを何回も回して、中央値をとる
- Python リファレンスと比べる(`uv run python -m timeit` や、API の結果の `elapsed_ms`)
- パラメータを総当たりにすると差がはっきりする(例:短期 2〜50 日 × 長期 10〜200 日)。これが次の GPU 版の出発点になる
- ビルドは Release(既定)。`-O3` や `-march=native` を試すのはいいが、`-ffast-math` は答えが変わるので使わない
- 結果は `docs/benchmarks.md` に表で残す(環境:CPU・コンパイラ・オプションも書く)

---

## M8:Python から呼べるようにする

`engine/bindings/` に pybind11 のモジュール `backtest_cpp` を作ると、API の受け口(`backend/engines.py`)がそれを見つけて、
画面の「確認」の手順で「C++ CPU 版」が選べるようになる。返す形は `docs/cpp/contract.md` の最後に書いてある。

pybind11 のつなぎ込みは Claude が書いてよい範囲。M6 まで終わったら、Claude Code に
「engine/cpp の run_ma_cross を pybind11 で backtest_cpp として呼べるようにして。engine/cpp は変更しないで」と頼む。
出来上がったコードは自分で読んで、どう変換しているかを説明できるようにしておく。

---

## 困ったとき

**`cpp-tutor` に聞く**(Claude Code の中で)

```
cpp-tutor に、M3 のヒントを1段階目だけ出してもらって
cpp-tutor に、このコンパイルエラーの意味を説明してもらって(エラーを貼る)
cpp-tutor に、engine/cpp/src/engine.cpp をレビューしてもらって。直し方のコードは書かずに、どこが仕様と違うかだけ
```

`cpp-tutor` は答えのコードを書かない設定になっている。ヒントは「方針 → 使う機能 → 擬似コード」の順に、頼んだ分だけ出す。

**違いを1行ずつ見る**

```bash
make cpp-case CASE=h07_split_while_holding
```

最初に違った行の日付が出るので、その日の値を `engine/reference/` で追いかける(Python の方に `print` を入れて比べてよい。終わったら消す)。

**メモリの壊れ方を見つける**

```bash
cmake -S . -B build-debug -G Ninja -DCMAKE_BUILD_TYPE=Debug \
  -DCMAKE_CXX_FLAGS="-fsanitize=address,undefined -fno-omit-frame-pointer"
cmake --build build-debug
BACKTEST_CPP_CLI=build-debug/engine/cpp/backtest_cli make test-cpp
```

範囲外の添字や、初期化していない値を使ったときに、どの行かを教えてくれる。

## よくある落とし穴

| 症状 | よくある原因 |
|---|---|
| シグナルの日付が1日ずれる | 窓の範囲の off-by-one(`k - window + 1` から `k` まで) |
| 権利落ちの日だけシグナルが違う | D(t') を t の基準で計算し直している / CumAdj の掛ける順番 |
| 株数が1単位違う | 2.7 の補正を忘れた / `lots` を `int` にした |
| 分割後の株数が1株違う | 調整係数をそのまま割り算して切り捨てた(p/q に戻していない) |
| p/q が違う | `std::round` を使った / `p / q` が整数の割り算になっている |
| 小数の末尾がわずかに違う | 足す順番が違う / `float` を使った / FMA が効いている |
| 年率リターンが空欄にならない | `std::isfinite` で確かめていない |
| たまに落ちる | 有効日がない日に `close` の `std::optional` を `*` で取り出した |

## このガイドを終えたら

- 面接で話せるようになること:`docs/interview.md`
- 次は GPU:`docs/gpu-plan.md`(パラメータの総当たりを CUDA で並列にする)
