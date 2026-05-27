# Market Radar 📊

全球族群起漲偵測 + 跨市場連動選股儀表板（台股 MVP）

## 🚀 Live Demo

部署於 Streamlit Community Cloud（部署完成後填入連結）。

## 功能

- **族群熱力圖**：47 大產業 + 422 上中下游細項 + 48 概念股 + 25 跨國供應鏈，四軸視覺化
- **RS 強度排行**：相對大盤 RS、起漲確認 / 候選狀態
- **族群輪動象限**：RS 強度 × RS 動能，看資金從哪輪到哪
- **個股詳細頁**：K 線 + 法人 + 融資 + 所屬族群 + 公司基本資料 + 相關新聞
- **自選股管理**：CSV 匯入匯出
- **每日自動更新**：可整合 GitHub Actions cron

詳細設計請見 [`docs/TAXONOMY.md`](docs/TAXONOMY.md)（股票分類體系規範）與 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)（雲端部署）。

## 專案結構

```
market_radar/
├── config/                # 設定檔
│   ├── settings.yaml      # 起漲規則等
│   └── taxonomy/tw/       # 四軸分類定義
├── connectors/tw/         # 台股資料源（價格、法人、融資、公司基本資料）
├── db/                    # SQLite schema + 初始化
├── compute/               # 族群指數、起漲判定、taxonomy sync
├── scrapers/              # 新聞、MoneyDJ 概念股
├── scripts/               # CLI 入口（ingest、compute、build_taxonomy）
├── ui/                    # Streamlit 儀表板
│   ├── app.py             # 主頁（大盤總覽）
│   └── pages/             # 5 個頁面
├── data/                  # SQLite 檔（git 上以 .gz 壓縮）
├── tpex_ic_crawl/         # TPEx 產業價值鏈爬蟲
└── docs/                  # 設計文件
```

## 本機開發

### 1. 建立虛擬環境並安裝依賴

```bash
cd market_radar
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. 初始化資料庫

如果你 clone 下來時 `data/market.db.gz` 已存在，跑 App 會自動解壓：

```bash
python bootstrap_db.py     # 把 .gz 解開
```

或從頭建立：

```bash
python -m db.init_db
python -m scripts.ingest_daily          # 抓全市場（15~30 分鐘）
python -m scripts.compute_themes        # 算族群指標
```

### 3. 跑 Streamlit

```bash
PYTHONPATH=. streamlit run ui/app.py
```

打開 http://localhost:8501

## 雲端部署

部署到 Streamlit Community Cloud 完整流程見 [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)。

簡版：
1. Push 到 GitHub public repo
2. 到 https://share.streamlit.io connect repo
3. Main file path 填 `ui/app.py`
4. Deploy → 等 5 分鐘 → 拿到網址

DB 以 `data/market.db.gz`（27MB）儲存於 repo，App 啟動時由 `bootstrap_db.py` 自動解壓。

## 每日資料更新

### 🤖 自動模式（推薦）

`.github/workflows/daily-update.yml` 每天台北 16:00（UTC 08:00）自動跑：
1. 抓今日股價（yfinance）
2. 抓三大法人 / 融資（若 GitHub IP 沒被擋）
3. 重算族群指標
4. 重壓 `data/market.db.gz`
5. Commit + push 回 main → Streamlit Cloud 自動重部署

可以隨時到 GitHub repo → **Actions** tab → **每日資料更新** → **Run workflow** 手動觸發。

### 🛠️ 手動模式

```bash
python -m scripts.ingest_daily --incremental
python -m scripts.compute_themes
gzip -9 -k -f data/market.db
git add data/market.db.gz && git commit -m "data: $(date +%F)" && git push
```

## 文件

- [`docs/TAXONOMY.md`](docs/TAXONOMY.md) — 四軸分類體系完整規範
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — Streamlit Cloud 部署 + 每日自動更新設定
- [`tpex_ic_crawl/產業鏈網站素材/README.md`](tpex_ic_crawl/產業鏈網站素材/README.md) — TPEx 爬蟲資料說明
