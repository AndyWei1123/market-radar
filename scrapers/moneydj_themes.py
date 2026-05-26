"""概念股 / 供應鏈半自動匯入工具（W4-5）。

外部來源（MoneyDJ / Yahoo / Goodinfo）多採 JS 動態渲染或反爬，直接 scraping 不穩定。
本工具改為「半人工」模式：

  1. 你從任一網站複製概念股清單，貼成簡單 TSV（tab 分隔）格式
  2. 工具讀檔 → 驗證 stock_id 存在於 DB → 寫入 config/themes.suggested.yaml
  3. 你 review 後手動把要保留的合併進 config/themes.yaml

TSV 格式範例（檔頭可省）：
    theme_id    name    market_scope    stock_ids
    nuclear     核能      TW              2603,2606,1310
    led_lighting LED      TW              2448,2421

用法：
    python -m scrapers.moneydj_themes --import path/to/list.tsv
    python -m scrapers.moneydj_themes --merge          # 把 suggested 合併進主檔（互動式）

未來若 MoneyDJ / Yahoo / Goodinfo 解出 anti-bot 路徑，可在 fetch_from_*() 補實作。
"""
from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from db.init_db import get_conn, init_db

log = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SUGGESTED_YAML = CONFIG_DIR / "themes.suggested.yaml"
MAIN_YAML = CONFIG_DIR / "themes.yaml"


@dataclass
class ConceptTheme:
    theme_id: str
    name: str
    market_scope: str = "TW"
    source: str = "manual_import"
    members_tw: list[str] = field(default_factory=list)
    members_us: list[str] = field(default_factory=list)


def _existing_stocks(conn: sqlite3.Connection) -> set[str]:
    cur = conn.execute("SELECT stock_id FROM stocks WHERE market='TW'")
    return {r[0] for r in cur.fetchall()}


def parse_tsv(path: Path) -> list[ConceptTheme]:
    """讀 TSV：theme_id, name, market_scope, stock_ids（逗號分隔）"""
    out: list[ConceptTheme] = []
    with path.open(encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="\t")
        rows = list(reader)
    # 自動偵測標頭
    start = 0
    if rows and rows[0] and rows[0][0].lower() in ("theme_id", "id"):
        start = 1
    for row in rows[start:]:
        if len(row) < 4 or not row[0].strip():
            continue
        tid = row[0].strip()
        name = row[1].strip()
        scope = (row[2].strip() or "TW").upper()
        ids_raw = row[3]
        members = [x.strip() for x in ids_raw.replace("，", ",").split(",") if x.strip()]
        if scope == "GLOBAL" and len(row) >= 5:
            us_ids = [x.strip() for x in row[4].replace("，", ",").split(",") if x.strip()]
        else:
            us_ids = []
        out.append(ConceptTheme(
            theme_id=tid, name=name, market_scope=scope,
            members_tw=members if scope in ("TW", "GLOBAL") else [],
            members_us=us_ids,
        ))
    return out


def validate(themes: list[ConceptTheme]) -> tuple[list[ConceptTheme], dict]:
    """過濾掉不存在於 DB 的 TW stock_id；回傳 (validated, report)。"""
    with get_conn() as conn:
        existing = _existing_stocks(conn)
    report = {"total_themes": len(themes), "valid_themes": 0,
              "total_ids": 0, "valid_ids": 0, "missing": []}
    out = []
    for t in themes:
        valid_tw = []
        for sid in t.members_tw:
            report["total_ids"] += 1
            if sid in existing:
                valid_tw.append(sid)
                report["valid_ids"] += 1
            else:
                report["missing"].append(f"{t.theme_id}/TW/{sid}")
        if valid_tw or t.members_us:
            t.members_tw = valid_tw
            out.append(t)
            report["valid_themes"] += 1
    return out, report


def write_suggested(themes: list[ConceptTheme]) -> int:
    SUGGESTED_YAML.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "_note": (
            "由 moneydj_themes.py 半自動匯入產生。\n"
            "請 review 後挑選要保留的，手動合併進 themes.yaml。\n"
            "（或執行 python -m scrapers.moneydj_themes --merge 走互動式合併）"
        ),
        "themes": [
            {
                "id": t.theme_id, "name": t.name,
                "market_scope": t.market_scope, "source": t.source,
                "members": {"TW": t.members_tw} | (
                    {"US": t.members_us} if t.members_us else {}
                ),
            }
            for t in themes
        ],
    }
    with SUGGESTED_YAML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, allow_unicode=True, sort_keys=False)
    return len(themes)


def cli_import(tsv_path: str) -> None:
    init_db(reset=False)
    path = Path(tsv_path)
    if not path.exists():
        log.error(f"找不到檔案：{path}")
        return
    themes = parse_tsv(path)
    log.info(f"📋 從 {path} 讀到 {len(themes)} 個主題")
    validated, report = validate(themes)
    log.info(f"驗證結果：{report['valid_themes']} 主題、"
             f"{report['valid_ids']}/{report['total_ids']} IDs OK；"
             f"缺漏 {len(report['missing'])} 筆")
    if report["missing"]:
        log.info(f"  缺漏範例：{report['missing'][:5]}")
    n = write_suggested(validated)
    log.info(f"✅ 已寫入 {SUGGESTED_YAML}（{n} 主題）")
    log.info("接下來可：1) 直接編輯 suggested 檔再合併、"
             "2) 跑 python -m scrapers.moneydj_themes --merge 走互動式")


def cli_merge() -> None:
    """互動式：把 themes.suggested.yaml 的主題逐個提示合併到 themes.yaml。"""
    if not SUGGESTED_YAML.exists():
        log.error(f"找不到建議檔 {SUGGESTED_YAML}")
        return
    with SUGGESTED_YAML.open(encoding="utf-8") as f:
        sug = yaml.safe_load(f) or {}
    with MAIN_YAML.open(encoding="utf-8") as f:
        main = yaml.safe_load(f) or {}

    sug_list = sug.get("themes", [])
    main_list = main.get("themes", [])
    main_ids = {t["id"] for t in main_list}

    accepted = 0
    for st in sug_list:
        if st["id"] in main_ids:
            print(f"⚠️ {st['id']} 已存在於 themes.yaml，跳過")
            continue
        n_tw = len(st["members"].get("TW", []))
        ans = input(f"加入 [{st['id']}] {st['name']}（{n_tw} 檔）? [y/N] ").strip().lower()
        if ans == "y":
            main_list.append(st)
            accepted += 1
    main["themes"] = main_list
    with MAIN_YAML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(main, f, allow_unicode=True, sort_keys=False)
    log.info(f"✅ 合併完成，新增 {accepted} 個主題到 themes.yaml")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--import", dest="tsv", help="從 TSV 匯入並產生 suggested.yaml")
    g.add_argument("--merge", action="store_true", help="互動合併 suggested → 主檔")
    args = p.parse_args()
    if args.tsv:
        cli_import(args.tsv)
    elif args.merge:
        cli_merge()


if __name__ == "__main__":
    main()
