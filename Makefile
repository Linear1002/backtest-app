# よく使うコマンドをまとめた Makefile。使い方は CLAUDE.md の「コマンド」欄を参照。

BUILD_DIR := build

.PHONY: setup test lint dev-api dev-web data-symbols data-fetch data-info data-check golden test-cpp cpp-case

# 依存ライブラリのインストールと C++ のビルド設定(最初に1回、依存が変わったときに実行)
# --locked:uv.lock を勝手に書き換えない(CI と同じ)。依存を変えるときは uv add / uv lock を使う
setup: $(BUILD_DIR)/CMakeCache.txt
	uv sync --locked
	npm ci --prefix frontend

# C++ のビルド設定。build/ が無いときだけ実行される
$(BUILD_DIR)/CMakeCache.txt:
	cmake -S . -B $(BUILD_DIR) -G Ninja

# Python のテスト、C++ のビルド・テスト、画面の関数のテスト
test: $(BUILD_DIR)/CMakeCache.txt
	uv run pytest
	cmake --build $(BUILD_DIR)
	ctest --test-dir $(BUILD_DIR) --output-on-failure
	npm --prefix frontend test

# Python(ruff)と frontend(ESLint)の静的チェック
lint:
	uv run ruff check .
	uv run ruff format --check .
	npm --prefix frontend run lint

# API サーバー(http://localhost:8000)
dev-api:
	uv run uvicorn backend.main:create_app --factory --reload --port 8000

# 画面の開発サーバー(http://localhost:3000)
dev-web:
	npm --prefix frontend run dev

# --- 株価データ(docs/data.md)。J-Quants を使うときは .env に JQUANTS_API_KEY が必要 ---

# J-Quants の銘柄一覧を取得して data/jquants/ に保存する(最初に1回。数分かかることがある)
data-symbols:
	uv run python -m backend.marketdata symbols

# 日足を取得して保存する。例: make data-fetch SYMBOLS="TSE:7203 TSE:6758"
data-fetch:
	uv run python -m backend.marketdata fetch $(SYMBOLS)

# 保存済みデータの範囲と権利落ちを表示する。例: make data-info SYMBOL=DEMO:1003
data-info:
	uv run python -m backend.marketdata info $(SYMBOL)

# docs/mvp.md 3.1 の「要確認」(調整係数の桁数など)を実データで調べる(10分ほどかかる)
data-check:
	uv run python -m backend.marketdata check-assumptions

# --- C++ 版エンジンの答え合わせ(docs/cpp/README.md) ---

# 段階1に取り組んでいる間は engine/cpp/STAGE に 1 と書いておく(CI も同じファイルを読む)
STAGE ?= $(shell cat engine/cpp/STAGE 2>/dev/null || echo 2)

# 正解データ(tests/golden)をリファレンス実装で作り直す
golden:
	uv run python scripts/make_golden.py

# C++ 版をビルドして、すべてのゴールデンケースと比べる。段階1だけなら make test-cpp STAGE=1
test-cpp: $(BUILD_DIR)/CMakeCache.txt
	cmake --build $(BUILD_DIR)
	BACKTEST_CPP_STAGE=$(STAGE) uv run pytest tests/python/test_golden.py -k cpp -v

# 1つのケースだけ C++ 版で動かして比べる。例: make cpp-case CASE=h01_round_trip
cpp-case: $(BUILD_DIR)/CMakeCache.txt
	cmake --build $(BUILD_DIR)
	rm -rf $(BUILD_DIR)/case-out
	-$(BUILD_DIR)/engine/cpp/backtest_cli tests/golden/cases/$(CASE)/input $(BUILD_DIR)/case-out
	uv run python -m engine.reference.compare tests/golden/cases/$(CASE)/expected $(BUILD_DIR)/case-out
