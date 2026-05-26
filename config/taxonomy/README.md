# Taxonomy 快速指引

> 完整規範請看 **`docs/TAXONOMY.md`**。本檔僅快速速查。

## 目錄結構

```
tw/    台股
  sectors.yaml      🤖 自動產生 — TPEx 47 大產業
  segments.yaml     🤖 自動產生 — 上中下游 422 細項
  themes.yaml       ✋ 手動 — 概念股
  chains.yaml       ✋ 手動 — 供應鏈
us/    (預留)
global/ (預留)
```

## 常見指令

```bash
# 重建 TPEx 分類（爬蟲跑完後）
python scripts/build_tw_taxonomy.py

# 同步進 DB + 重算族群指標
python scripts/compute_themes.py

# 只同步分類、不重抓大盤（編完 themes/chains 後）
python scripts/compute_themes.py --no-index
```

## 修改 themes.yaml 範例

```yaml
themes:
  - id: my_new_theme
    name: 我的新題材
    market_scope: TW
    source: manual
    members:
      TW: ["2330", "2317"]
```

## ⚠️ 不要做的事

- ❌ 手動編 `sectors.yaml` / `segments.yaml`（會被 build script 覆寫）
- ❌ 編 `config/themes.yaml` / `config/chains.yaml`（v0.3 deprecated）
- ❌ 直接 INSERT 到 themes 表（請走 yaml + loader）

詳細邏輯、清洗規則、跨市場擴充 → `docs/TAXONOMY.md`
