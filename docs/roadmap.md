# ロードマップ

MVP(東証上場株・日足・移動平均クロス)完成までの順番。各段階は1つ以上のブランチ・PRに分けて進める。
仕様は `docs/mvp.md` を正とする。

| # | 段階 | 担当 | 完了の目安 | 状態 |
|---|------|------|-----------|------|
| 1 | 開発環境構築 | Claude | `make test` / `make lint` が通り、CI が緑 | できた |
| 2 | 株価データ取得 | Claude | J-Quants API から日足と分割情報を取得し、`data/` に Parquet で保存できる。APIキーは `.env` から読む | できた |
| 3 | Pythonリファレンス実装 | Claude | `engine/reference/` に読んで正しいとわかる実装があり、境界ケースを含む pytest が通る | できた(正解データ60ケース) |
| 4 | FastAPI | Claude | 銘柄・条件を受け取り、リファレンス実装でバックテストした結果を返す API がある | できた |
| 5 | 画面 | Claude | 銘柄・条件の入力 → 実行 → 成績表とグラフの表示が日本語UIでできる | できた(画面〜API の通しのテストも CI で) |
| 6 | C++エンジン | **開発者** | マイルストーン M0〜M8(`docs/cpp/README.md`)を通して、正解データとの一致テストが通る | 取り組み中 |
| 7 | 仕上げ | 両方 | README・デモ・性能計測の結果を整え、ポートフォリオとして見せられる | README・コードの読み方ガイド(`docs/tour.md`)はできた。性能計測は C++ 版のあと |
| 8 | パラメータの総当たり(Python 版・API・画面) | Claude | 仕様 `docs/sweep.md`、Python の総当たり(正解)と正解データ24ケース、ジョブの API、ヒートマップの画面 | できた(`docs/gpu-plan.md` の G1・G7) |
| 9 | C++ 版・GPU 版の総当たり | **開発者** | `docs/gpu-plan.md` の G0・G2〜G6・G8 | C++ エンジン(段階6)のあと |

## 6. C++エンジンの進め方(開発者が書く)

Claude は方針・ヒント・レビューだけを出す(CLAUDE.md の役割分担)。ヒントがほしいときは `cpp-tutor` サブエージェントに聞く。

- 道のりは `docs/cpp/README.md` のマイルストーン M0〜M8。入出力の約束は `docs/cpp/contract.md`
- いま取り組んでいるマイルストーンを `engine/cpp/MILESTONE` に書くと、`make test-cpp` と CI が、そこまでに合格するはずのケース・項目だけを正解データ(`tests/golden/`)と比べる
- 大きく分けると、**段階1:分割なし**(シグナル・約定・成績指標が一致)→ **段階2:分割あり**(分割・併合の日の持ち株数の変更 docs/mvp.md 2.8 まで一致)
- 最後に pybind11 で Python から呼び出せるようにし、画面の「計算エンジン」で Python 版と切り替えられるようにする(`backend/engines.py` はつなぐ準備ができている)

## 8・9. 総当たりと GPU 版の進め方

- 総当たりの仕様・Python 版(正解)・正解データ(`tests/golden/sweeps/`)・API・画面はできている。いまは Python を複数のプロセスで動かして計算している(上限 2,000通り)
- C++ 版が終わってから、総当たりの C++ 版(`sweep_cli`。答え合わせのファイルの形は `docs/sweep.md` 11章)→ CUDA 版の順に進める。
  計画は `docs/gpu-plan.md`(何を並列にするか、CPU と結果を一致させるための決まり、過剰最適化への備え、マイルストーン G0〜G8)
- できたら `backend/engines.py` の `list_sweep_engines` と `backend/sweeps.py` でつなぐ(画面は変えなくてよい)
