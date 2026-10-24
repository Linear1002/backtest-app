"""株価データ層(docs/mvp.md 3章)。

- models.py     共通形式(銘柄ID・日足・市場ごとの設定)
- source.py     データソースのインターフェースとエラー
- synthetic.py  架空データ(DEMO市場)。APIキーなしで動く
- jquants.py    J-Quants API(V2)のクライアントとデータソース
- store.py      Parquet での保存・読み込み
- service.py    複数のデータソースをまとめる窓口(API 層はこれだけを使う)
"""
