"""[Deprecated v0.3] 此檔保留為相容層，請改用 compute.taxonomy_loader。

新分類體系統一由 compute/taxonomy_loader.py 處理：
  - sectors  / segments  : 來自 TPEx 自動爬取
  - themes   / chains    : 來自 config/taxonomy/<market>/ 手動 YAML
"""
from __future__ import annotations

import warnings

from compute.taxonomy_loader import (  # noqa: F401  (re-export)
    sync_all, sync_sectors, sync_segments, sync_themes, sync_chains,
)


def __getattr__(name: str):
    # 給仍 import 舊符號的 code path 警告一次
    warnings.warn(
        f"compute.themes_loader.{name} is deprecated, use compute.taxonomy_loader",
        DeprecationWarning, stacklevel=2,
    )
    raise AttributeError(name)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(sync_all())
