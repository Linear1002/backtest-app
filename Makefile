# よく使うコマンドをまとめた Makefile。使い方は CLAUDE.md の「コマンド」欄を参照。

BUILD_DIR := build

.PHONY: setup test lint dev-api dev-web

# 依存ライブラリのインストールと C++ のビルド設定(最初に1回、依存が変わったときに実行)
# --locked:uv.lock を勝手に書き換えない(CI と同じ)。依存を変えるときは uv add / uv lock を使う
setup: $(BUILD_DIR)/CMakeCache.txt
	uv sync --locked
	npm ci --prefix frontend

# C++ のビルド設定。build/ が無いときだけ実行される
$(BUILD_DIR)/CMakeCache.txt:
	cmake -S . -B $(BUILD_DIR) -G Ninja

# Python のテストと C++ のビルド・テスト
test: $(BUILD_DIR)/CMakeCache.txt
	uv run pytest
	cmake --build $(BUILD_DIR)
	ctest --test-dir $(BUILD_DIR) --output-on-failure

# Python(ruff)と frontend(ESLint)の静的チェック
lint:
	uv run ruff check .
	uv run ruff format --check .
	npm --prefix frontend run lint

# API サーバー(http://localhost:8000)
dev-api:
	uv run uvicorn backend.main:app --reload --port 8000

# 画面の開発サーバー(http://localhost:3000)
dev-web:
	npm --prefix frontend run dev
