# Market Radar 股票分類規範（Taxonomy v0.3.1）

> 本文件是 Market Radar 全部「股票分類體系」的單一真實來源（single source of truth）。
> 包含：邏輯、資料庫、維護流程、資料清洗規則、跨市場擴充。
> 任何分類相關的修改都應該先讀完本文件再動手。

最後更新：v0.3.1（2026-05）

---

## 目錄

1. [設計哲學](#1-設計哲學)
2. [四個分類軸](#2-四個分類軸)
3. [資料庫 schema](#3-資料庫-schema)
4. [檔案佈局](#4-檔案佈局)
5. [資料流（爬取 → YAML → DB → UI）](#5-資料流)
6. [維護流程（4 個常見任務）](#6-維護流程)
7. [資料清洗 & 分類判斷規則](#7-資料清洗--分類判斷規則)
8. [跨市場擴充（美股、日股…）](#8-跨市場擴充)
9. [常見問題](#9-常見問題-faq)
10. [變更紀錄](#10-變更紀錄)

---

## 1. 設計哲學

### 為什麼要這樣切？

操盤手要回答的不是「這檔股票是哪個產業」，而是 **「資金正從哪裡輪到哪裡」**。
單一分類太粗（"電子業"），單一概念股太雜（PCB 漲跟散熱漲是不同事）。
所以我們用 **四個獨立軸 × 多對多** 同時切視角。

### 三條鐵律

1. **官方來源優先**：sector / segment 一律由官方爬取自動產生，**絕不手動編輯 yaml**。
2. **手動軸保持小而精**：theme / chain 是策略性概念，每個都應該對應一個明確的交易論述。
3. **schema 通用、市場分檔**：DB 不為市場分表；YAML 按市場分檔。新增國家不動 schema。

---

## 2. 四個分類軸

| Axis (`classification_type`) | 中文 | 來源 | 維護方式 | 數量 | 範例 |
|---|---|---|---|---|---|
| `sector` | 大產業 | TPEx ic.tpex.org.tw | 🤖 自動爬取 | TW: 47 | 半導體 / PCB / 太陽能 |
| `segment` | 上中下游細項 | TPEx ic.tpex.org.tw | 🤖 自動爬取 | TW: 422 | IC設計 / IC封測 / ABF載板 / 煤鐵礦砂 |
| `theme` | 概念股 | 手動 YAML | ✋ 人工 | TW: 48 | CoWoS / HBM / 矽光子 / AI 伺服器 |
| `chain` | 供應鏈 | 手動 YAML | ✋ 人工 | TW: 25 | 輝達鏈 / 台積電鏈 / Apple 鏈 |

### 軸的職責切分

- **`sector`** ── 「這檔在政府/官方眼中算哪個產業？」**全市場 100% 覆蓋**，每檔股票剛好一個 sector。
- **`segment`** ── 「在產業鏈的哪一段？上游材料、中游製造、還是下游應用？」一檔股票可在多個 segment（例：台達電同時在「電源管理 IC」、「IC 模組」、「IC 通路」）。
- **`theme`** ── 「市場現在熱炒的『故事』是什麼？」隨著市場敘事更新（v0.3 後不再隨意新增題材，每個 theme 都要有交易邏輯）。
- **`chain`** ── 「靠誰吃飯？」以某家**錨股**（通常是國外大廠）為核心，列出受惠的台股供應商。

### 個股可同時對應多軸

範例 **2330 台積電**：

```
[sector]  半導體                                 (RS  95)
[segment] IC/晶圓製造  (中游)                      (RS 161)  ← 新增的細顆粒視角
[theme]   CoWoS 先進封裝                          (RS 179)
[theme]   HBM 高頻寬記憶體                        (RS 123)
[theme]   矽光子                                 (RS 122)
[theme]   AI 伺服器                               (RS  94)
[chain]   台積電鏈 (2330)                         (RS 146)
[chain]   Samsung 鏈 / Intel 鏈 / AMD 鏈…         (多條)
```

每一條代表一種「為什麼這檔可能漲」的論述。儀表板的價值就在於同時看這些。

---

## 3. 資料庫 schema

統一儲存在 `themes` 表（命名為 themes 是歷史原因，實際存全部 4 軸）：

```sql
CREATE TABLE themes (
    theme_id            TEXT PRIMARY KEY,
    theme_name          TEXT NOT NULL,
    classification_type TEXT NOT NULL,      -- 'sector' / 'segment' / 'theme' / 'chain'
    market_scope        TEXT NOT NULL,      -- 'TW' / 'US' / 'GLOBAL'
    description         TEXT,
    source              TEXT,               -- 'official' / 'manual' / 'moneydj' / 'tpex'
    taxonomy_source     TEXT,               -- 同來源更細的標記，見下表
    parent_theme_id     TEXT,               -- segment → sector 的階層關係
    segment_stage       TEXT,               -- '上游' / '中游' / '下游' 或 TPEx 自訂分段（如 '資安產品'）
    external_code       TEXT,               -- 官方外部代碼（TPEx ic 碼 / GICS code）
    display_order       INTEGER DEFAULT 0,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- index
CREATE INDEX idx_themes_type   ON themes(classification_type);
CREATE INDEX idx_themes_scope  ON themes(market_scope);
CREATE INDEX idx_themes_parent ON themes(parent_theme_id);
CREATE INDEX idx_themes_source ON themes(taxonomy_source);
```

`theme_membership` 多對多關聯：

```sql
CREATE TABLE theme_membership (
    theme_id   TEXT NOT NULL,
    stock_id   TEXT NOT NULL,
    market     TEXT NOT NULL,             -- TW / US / JP / HK
    weight     REAL DEFAULT 1.0,           -- 預留未來給加權指數用，目前全 1.0
    PRIMARY KEY (theme_id, stock_id, market)
);
```

### `taxonomy_source` 列舉值

| 值 | 含義 | 對應軸 |
|---|---|---|
| `tpex_sector` | 來自 TPEx 47 大產業 | sector |
| `tpex_segment` | 來自 TPEx 上中下游細項 | segment |
| `twse_listing` | (deprecated v0.3) 來自 TWSE listing 分類 | sector |
| `manual_theme` | 手動定義概念股 | theme |
| `manual_chain` | 手動定義供應鏈 | chain |
| `gics_sector` | (預留) 美股 GICS 大產業 | sector |
| `gics_industry` | (預留) 美股 GICS industry-group | segment |
| `topix_33` | (預留) 日股 TOPIX 33 業種 | sector |

### `theme_id` 命名約定

```
sector_<market>_<code>      sector_tw_D000        # TPEx 半導體
segment_<market>_<code>     segment_tw_D100       # TPEx IC設計
theme_<id>                  theme_cowos           # 概念股（理論上不分市場）
chain_<id>                  chain_nvda_chain      # 供應鏈（理論上跨市場）
```

⚠️ 不要手動編 ID，loader 會自動產生。

---

## 4. 檔案佈局

```
market_radar/
├── tpex_ic_crawl/                       ← 爬蟲（外部來源 raw data）
│   ├── 01_discover_codes.py
│   ├── 02_fetch_all.sh
│   ├── ... (爬蟲流程腳本)
│   ├── html/industry/{ic}.html          ← 原始 HTML
│   └── 產業鏈網站素材/結構化資料/
│       ├── codes.json                   ← 47 產業 ↔ 2,405 股票
│       ├── industries.json              ← 每個產業的鏈結構 + 政策
│       └── stocks_meta.json             ← 股票名稱 ↔ 代碼
│
├── config/taxonomy/
│   ├── README.md                        ← 速查
│   ├── tw/
│   │   ├── sectors.yaml                 🤖 自動產生
│   │   ├── segments.yaml                🤖 自動產生
│   │   ├── themes.yaml                  ✋ 手動編輯
│   │   └── chains.yaml                  ✋ 手動編輯
│   ├── us/   (預留)
│   └── global/  (預留：跨市場 chains)
│
├── scripts/
│   ├── build_tw_taxonomy.py             ← TPEx → yaml
│   ├── compute_themes.py                ← yaml → DB + 指標計算
│   └── ...
│
├── compute/
│   └── taxonomy_loader.py               ← yaml → DB 的 sync 邏輯（核心）
│
├── db/
│   ├── schema.sql                       ← schema 源碼
│   └── init_db.py                       ← schema + migrations
│
└── docs/
    └── TAXONOMY.md                      ← 你正在看
```

---

## 5. 資料流

```
┌─────────────────────────────────────────────────────────────────┐
│                    raw data                                       │
│  TPEx (ic.tpex.org.tw)                                            │
│     ↓ 爬蟲 (tpex_ic_crawl/01~06_*.py)                              │
│  HTML + codes.json + industries.json + stocks_meta.json           │
└─────────────────────────────────────────────────────────────────┘
                              ↓ scripts/build_tw_taxonomy.py
┌─────────────────────────────────────────────────────────────────┐
│                  config/taxonomy/tw/                              │
│   sectors.yaml     ← 47 個                                        │
│   segments.yaml    ← 422 個（含 parent_sector + stage）           │
│   themes.yaml      ← ~50 個（手動）                                │
│   chains.yaml      ← ~25 個（手動）                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓ compute/taxonomy_loader.sync_all()
┌─────────────────────────────────────────────────────────────────┐
│                       SQLite DB                                   │
│   themes (542 列)                                                 │
│   theme_membership (~3 萬列 — 含多對多展開)                       │
└─────────────────────────────────────────────────────────────────┘
                              ↓ compute/breakout.compute_all()
┌─────────────────────────────────────────────────────────────────┐
│   theme_daily_metrics                                             │
│   (~13 萬列 = 542 themes × 240 trading days)                      │
│   含 RS、上漲天數、起漲狀態、5/20 日漲跌、站上 20MA 比例         │
└─────────────────────────────────────────────────────────────────┘
                              ↓ Streamlit UI 讀取
                       熱力圖 / RS 排行 / 詳細頁
```

---

## 6. 維護流程

### 6.1 例行更新 TPEx 官方分類（建議每月 / 每季）

TPEx 平台分類不常改，但偶有新增子分類或公司歸類調整。

```bash
# Step 1: 重新爬取 TPEx（30 分鐘）
cd tpex_ic_crawl
python 01_discover_codes.py
bash   02_fetch_all.sh
python 03_build_data_urls.py
python 04_parse_industry.py
bash   05_fetch_data_layer.sh
python 06_parse_companies.py

# Step 2: 從爬蟲結果產生 yaml（10 秒）
cd ..
python scripts/build_tw_taxonomy.py

# Step 3: 同步 + 重算指標
python scripts/compute_themes.py
```

執行後檢查 `logs/missing_stocks.log` 看是否有新股票 TPEx 已收錄但本機 DB 還沒有。
如有 → 跑 `python scripts/ingest_daily.py --bootstrap` 補抓。

### 6.2 新增 / 修改概念股 (theme)

只編 `config/taxonomy/tw/themes.yaml`：

```yaml
themes:
  - id: cowos                          # 唯一 ID（英數小寫，不要含中文）
    name: CoWoS 先進封裝               # 顯示名稱
    market_scope: TW                  # TW / US / GLOBAL
    source: manual                    # manual / moneydj
    members:
      TW: ["2330", "3661", "6147"]
      US: ["NVDA"]                    # 美股啟用時自動接上
    notes: |                          # （可選）trading thesis
      AI 算力擴張下，CoWoS 產能滿載拉動先進封裝設備需求。
```

> ⚠️ **加新題材前先問自己**：這個題材跟現有的 `theme_X` 是否大量重疊？若 >70% 成員重複，請考慮合併不要新增。

存檔後：

```bash
python scripts/compute_themes.py --no-index
```

刪除 yaml 中的項目會被自動清掉，不需要手動 SQL。

### 6.3 新增供應鏈 (chain)

編 `config/taxonomy/tw/chains.yaml`：

```yaml
chains:
  - id: nvda_chain
    name: 輝達鏈 (NVDA)
    market_scope: GLOBAL
    anchor: {market: US, stock_id: NVDA}     # 錨股
    members:
      TW: ["2330", "3231", "2382"]
      US: ["NVDA"]
    notes: |
      美股 NVDA 為錨股，台股以 AI 伺服器 ODM 與晶圓代工為主。
```

### 6.4 補抓某些股票（出現在 logs/missing_stocks.log）

```bash
python scripts/ingest_daily.py --bootstrap --stocks 6488,3711
python scripts/compute_themes.py --no-index
```

---

## 7. 資料清洗 & 分類判斷規則

這節是「為什麼分類長這樣」的決策準則。爭議時拿這節當依據。

### 7.1 Sector（大產業）—— 完全依官方

- **判斷依據**：TPEx `codes.json.stocks[stock_id]` 直接給的 industry_code。
- **不可手動修改**：一檔股票若不認同 TPEx 的歸類，**請改 theme 或 chain 來補敘事，不要動 sector**。
- **新股自動歸類**：新爬到的股票，下次 build 自動進對應 sector。
- **下市處理**：TPEx 不再列入 = 自動從 sector 移除（透過 `_delete_stale` 機制）。

### 7.2 Segment（上中下游細項）—— 取 TPEx 權威來源

- **名稱來源**：HTML `<div id="companyList_XXXX" title="名稱">` 的 `title` 屬性（v0.3.1 起）。
- **stage（上中下游）來源**：往上 traverse 找最近的 `<div class="chain-title-panel">`。
- **無 stage 的 segment**：有些產業（5100 區塊鏈、Y000 文創、U000 金融）沒有上中下游視覺結構，stage 設為空字串，UI 顯示成「未分上中下游」。**這是 TPEx 設計如此，不是 bug。**
- **跳過規則**（v0.3.1）：
  - ❌ 無 title 屬性 → 跳過（不允許用代碼當名稱）
  - ❌ 無 TW 成員 → 跳過（純外國公司的 segment）
  - ✓ 名稱與大產業相同 → 仍保留（這是 TPEx 的正常情況，例：「印刷電路板」sector 下有一個叫「印刷電路板」的 segment）

### 7.3 Theme（概念股）—— 手動精選

判斷一個 theme 該不該收的 checklist：

- ✅ **有明確交易論述**（一句話講得清為什麼這群會一起漲跌）
- ✅ **成員 ≥ 3 檔且 ≤ 30 檔**（太少 = 不像族群，太多 = 變成 sector）
- ✅ **跟現有 theme 重疊 < 70%**
- ❌ 避免「AI 概念股」這種太寬的 theme，請拆成 AI Server / CoWoS / HBM / 矽光子 等具體應用
- ❌ 避免「XX 受惠股」這種命名，請改成具體技術或產品

成員選股原則：
1. 該股的 **業務直接受惠** > 間接受惠
2. 公司公開 announce 過該業務 > 媒體推測
3. 營收占比 ≥ 5% 才入列（避免過度搭便車）

### 7.4 Chain（供應鏈）—— 以錨股為核心

- **anchor 必填**：每條 chain 都要綁定一檔錨股（通常是國外大廠或台股龍頭）。
- **成員入列標準**：該股有 **直接出貨給錨股** 或 **直接受惠於錨股下單**。
- **多重歸屬 OK**：2330 可以同時在 NVDA 鏈 / AMD 鏈 / Intel 鏈（事實上就是）。
- **錨股財報季更新**：當錨股法說有新供應商揭露時，補進 chain。

### 7.5 Missing Stock 處理

`logs/missing_stocks.log` 會列出「yaml 提到但 DB 沒有」的股票。原因：

| 原因 | 解法 |
|---|---|
| 新股還沒爬到 | 跑 `ingest_daily.py --bootstrap --stocks XXXX` |
| 下市股 | 從 yaml 移除該 stock_id |
| ID 寫錯（如 KY 股股號變動） | 修正 yaml |
| 該股是美股而 theme.market_scope=TW | 加 US: [...] 到 members |

### 7.6 重複 / 衝突處理

- **同一檔在多個 sector**：不可能（TPEx 一檔對一個 sector）。如果發生 = data bug。
- **同一檔在多個 segment**：正常（一家公司營業多段價值鏈）。
- **同一檔在 N 個 theme**：正常但若 N>10 表示要清理 theme 定義。

---

## 8. 跨市場擴充

### 8.1 加入美股

```
config/taxonomy/us/
├── sectors.yaml      ← 11 GICS Sectors
├── segments.yaml     ← ~25 GICS Industry Groups（細到 sub-industry 太碎）
├── themes.yaml       ← Mag 7 / SaaS / 半導體 ETF 成分…
└── chains.yaml       ← 跟 TW 共享或獨立都行
```

實作步驟：

1. **加 GICS 資料來源**：寫 `scripts/build_us_taxonomy.py` 從 [Wikipedia GICS](https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard) 或 [SEC OpenSubmissions](https://www.sec.gov/) 拿分類。
2. **stock_id 命名約定**：美股直接用 ticker（NVDA, AAPL）。
3. **在 `compute/taxonomy_loader.sync_all()` 加 `market='us'` 呼叫**。
4. **`stocks` 表加 US 股票**：`market='US'` 區分。
5. **DB 不動 schema**：`market_scope` 欄位已經支援。

### 8.2 加入日股

類似美股流程，但分類用 **TOPIX 33 業種**：

```
config/taxonomy/jp/sectors.yaml      ← TOPIX 33 業種
```

日本沒有 TPEx 那種價值鏈視覺化平台，segment 可選擇：
- 不做 segment 軸（jp 市場只有 sector / theme / chain）
- 或用 J-SIC（日本標準產業分類）的中分類當 segment

### 8.3 跨市場供應鏈

長期計畫：把 chain 集中放 `config/taxonomy/global/chains.yaml`，因為供應鏈本質就跨市場。

但 v0.3 仍放在 `tw/chains.yaml`（因為當前只用台股）。

---

## 9. 常見問題 FAQ

### Q1: 為什麼有的族群名字長得像「QG00」？
A: v0.3.1 之前的 bug，現已修復。所有 segment 都會從 HTML 的 `title` 屬性取得正確中文名。如果現在還看到，跑 `python scripts/build_tw_taxonomy.py && python scripts/compute_themes.py`。

### Q2: 為什麼有些 segment 沒有上中下游標記？
A: 不是所有產業都有上中下游結構。像「區塊鏈」、「文化創意」、「金融」這類產業在 TPEx 上沒有畫鏈狀圖，所以對應 segment 的 stage 是空的。UI 上會顯示成「未分上中下游」。

### Q3: 為什麼台積電屬於這麼多 chain？
A: 它的確同時是 NVDA、AMD、Intel、Apple、Samsung 等多家國際大廠的代工夥伴。chain 就是要呈現這種「靠誰吃飯」的多重關係。

### Q4: 我想加一個新概念股，應該編哪裡？
A: `config/taxonomy/tw/themes.yaml`。**不要編 `config/themes.yaml`**，那個檔已經 deprecated。

### Q5: missing_stocks.log 一直在累積，要怎麼清？
A: 它是 append-only log。可以直接 `rm logs/missing_stocks.log`，下次 sync 會重新寫入當下的 missing 清單。

### Q6: 我刪掉 yaml 的某個 theme，DB 還會有殘留嗎？
A: 不會。每次 `sync_themes()` 都會比對 yaml vs DB，移除已刪除的項目（透過 `_delete_stale`）。但 `theme_daily_metrics` 的歷史指標不會被刪（避免破壞歷史資料）。

### Q7: 新增第 6 個分類軸（例如「ESG 主題」）可以嗎？
A: 可以。步驟：
1. `classification_type` 列舉值多一個（例如 `esg`）
2. 在 `compute/taxonomy_loader.py` 加 `sync_esg()`
3. UI 的 `TYPE_LABEL` 字典加翻譯
4. 改各頁面的 `["sector", "segment", "theme", "chain"]` 加上 `"esg"`

設計目標：軸要少、要精，超過 6 個就過度切割。

---

## 10. 變更紀錄

### v0.3.1（當前）— 2026-05
- **修復 segment 名稱**：改用 HTML `title` 屬性，不再 fallback 用代碼當名稱（修掉 Y100 / QG00 顯示問題）。
- **修復 stage 偵測**：用 HTML 樹 traverse 找 `chain-title-panel`，現在 275 個 segment 能正確標記上中下游。
- **UI 加 segment 視覺化**：
  - 熱力圖「產業鏈細項」tab 改用「大產業 → 上中下游 → 細項」三層 treemap
  - RS 排行勾選 segment 時顯示「所屬大產業」「上中下游」欄
  - 個股詳細頁 segment 軸依大產業分群顯示，每個 chip 標 [上游/中游/下游]
- **新增本文件** `docs/TAXONOMY.md`

### v0.3 — 2026-05
- 新增 4 軸架構：sector / **segment** / theme / chain（新增 segment 軸）
- 重構檔案結構：`config/themes.yaml` / `config/chains.yaml` → `config/taxonomy/<market>/`
- 引入 TPEx 47 大產業 + 422 上中下游 segment（取代舊 TWSE listing 34 類）
- DB schema 加 5 欄位：`taxonomy_source` / `parent_theme_id` / `segment_stage` / `external_code` / `display_order`
- 新增 `scripts/build_tw_taxonomy.py` 自動 build 工具
- 重寫 `compute/taxonomy_loader.py`，舊 `themes_loader.py` 變相容 wrapper

### v0.2 — 2026-04
- 擴充 themes 到 48 個概念股
- 擴充 chains 到 25 個供應鏈

### v0.1 — 2026-03
- 初始三軸架構：sector（TWSE 34 listing 類別）/ theme / chain
