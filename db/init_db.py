"""初始化 SQLite 資料庫。

用法：
    python -m db.init_db                # 建立 data/market.db
    python -m db.init_db --reset        # 先刪除舊檔再建立
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "market.db"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


# 增量 schema 修補：新欄位、新索引。每次 init_db 都會跑（idempotent）。
# 加新欄位請在這裡 append；不要改舊欄位定義（會破壞既有資料）。
MIGRATIONS: list[tuple[str, str]] = [
    # (table, ALTER 子句)  ── 若欄位已存在會被略過
    ("themes", "ADD COLUMN taxonomy_source TEXT"),
    ("themes", "ADD COLUMN parent_theme_id TEXT"),
    ("themes", "ADD COLUMN segment_stage TEXT"),
    ("themes", "ADD COLUMN external_code TEXT"),
    ("themes", "ADD COLUMN display_order INTEGER DEFAULT 0"),
]
MIGRATION_INDEXES: list[str] = [
    "CREATE INDEX IF NOT EXISTS idx_themes_parent ON themes(parent_theme_id)",
    "CREATE INDEX IF NOT EXISTS idx_themes_source ON themes(taxonomy_source)",
]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """對既有 DB 加新欄位 / 索引（沒有則加，已有則跳過）。"""
    for table, alter in MIGRATIONS:
        if not _table_exists(conn, table):
            continue
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        col_name = alter.split()[2]  # "ADD COLUMN <name> ..."
        if col_name in cols:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} {alter}")
            print(f"[migrate] {table}: {alter}")
        except sqlite3.OperationalError as e:
            print(f"[migrate] skip {table} {alter}: {e}")
    for sql in MIGRATION_INDEXES:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            print(f"[migrate] skip index: {e}")
    conn.commit()


def init_db(reset: bool = False) -> Path:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"[init_db] removed {DB_PATH}")

    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(schema)
        _apply_migrations(conn)
        conn.commit()
    print(f"[init_db] ready: {DB_PATH}")
    return DB_PATH


def get_conn() -> sqlite3.Connection:
    """供其他模組使用的連線工廠。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="刪除現有 DB 後重建")
    args = parser.parse_args()
    init_db(reset=args.reset)
