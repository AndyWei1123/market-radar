"""Streamlit Cloud 啟動時自動把 data/market.db.gz 解壓成 data/market.db。

本機開發時 data/market.db 已存在，此 script 會偵測到並跳過。
"""
from __future__ import annotations

import gzip
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "market.db"
GZ_PATH = ROOT / "data" / "market.db.gz"


def ensure_db(force: bool = False) -> Path:
    """確保 data/market.db 存在；若否、從 .gz 解壓。"""
    DB_PATH.parent.mkdir(exist_ok=True)

    if DB_PATH.exists() and DB_PATH.stat().st_size > 1_000_000 and not force:
        return DB_PATH

    if not GZ_PATH.exists():
        raise FileNotFoundError(
            f"找不到 {DB_PATH} 也沒有 {GZ_PATH}。"
            "請先在本機跑過 `python -m db.init_db` 與 ingest 流程，再 push。"
        )

    print(f"[bootstrap] 解壓 {GZ_PATH.name} → {DB_PATH.name} ...")
    with gzip.open(GZ_PATH, "rb") as src, open(DB_PATH, "wb") as dst:
        shutil.copyfileobj(src, dst)
    print(f"[bootstrap] ✅ 完成 ({DB_PATH.stat().st_size // 1024 // 1024} MB)")
    return DB_PATH


if __name__ == "__main__":
    ensure_db(force=True)
