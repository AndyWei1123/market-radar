"""Config loader.

新版分類體系（v0.3）：
  config/taxonomy/<market>/sectors.yaml   ── 大產業
  config/taxonomy/<market>/segments.yaml  ── 上中下游細項
  config/taxonomy/<market>/themes.yaml    ── 概念股
  config/taxonomy/<market>/chains.yaml    ── 供應鏈

提供統一介面 load_taxonomy(market) 給 compute/taxonomy_loader 使用。
舊 API themes() / chains() 為相容層，預設讀 tw 市場。
"""
from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent
TAXONOMY_DIR = CONFIG_DIR / "taxonomy"

_cache: dict[str, dict] = {}


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    key = str(path)
    if key not in _cache:
        with path.open(encoding="utf-8") as f:
            _cache[key] = yaml.safe_load(f) or {}
    return _cache[key]


def settings() -> dict:
    return _read_yaml(CONFIG_DIR / "settings.yaml")


def load_taxonomy(market: str = "tw") -> dict:
    """讀單一市場的所有分類定義。

    回傳：
        {
            "sectors":  [...],   # items list from sectors.yaml
            "segments": [...],
            "themes":   [...],   # items from themes.yaml's "themes" key
            "chains":   [...],   # items from chains.yaml's "chains" key
        }
    """
    base = TAXONOMY_DIR / market.lower()
    sectors_doc = _read_yaml(base / "sectors.yaml")
    segments_doc = _read_yaml(base / "segments.yaml")
    themes_doc = _read_yaml(base / "themes.yaml")
    chains_doc = _read_yaml(base / "chains.yaml")
    return {
        "sectors":  sectors_doc.get("items", []),
        "segments": segments_doc.get("items", []),
        # themes/chains 為手動維護，沿用舊 key
        "themes":   themes_doc.get("themes", []),
        "chains":   chains_doc.get("chains", []),
    }


# ─────────── 向下相容 (deprecated, 但仍保留) ───────────
def themes() -> dict:
    """[deprecated] 改用 load_taxonomy('tw')['themes']"""
    return {"themes": load_taxonomy("tw")["themes"]}


def chains() -> dict:
    """[deprecated] 改用 load_taxonomy('tw')['chains']"""
    return {"chains": load_taxonomy("tw")["chains"]}


def load(name: str) -> dict:
    """[legacy] 讀 config/<name>.yaml；新分類請用 load_taxonomy()。"""
    return _read_yaml(CONFIG_DIR / f"{name}.yaml")
