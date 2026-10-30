"""FastAPI のエントリーポイント。"""

from fastapi import FastAPI

app = FastAPI(title="日本語バックテストアプリ API")


@app.get("/api/health")
def health() -> dict[str, str]:
    """サーバーが起動しているかの確認用。"""
    return {"status": "ok"}
