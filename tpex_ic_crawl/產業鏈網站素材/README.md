# 產業鏈網站素材

來源：[產業價值鏈資訊平台 ic.tpex.org.tw](https://ic.tpex.org.tw/)（櫃買中心+證交所）

## 資料夾結構

### 📁 結構化資料/（建站主用，直接拿來餵前端）

| 檔案 | 內容 | 怎麼用 |
|---|---|---|
| `industries.json` | 47 個產業，每個含：產業鏈簡介 (上游/中游/下游)、各區段對應廠商、政府相關政策全文 | 產業頁主資料源，直接 render 出價值鏈圖 + 公司清單 |
| `codes.json` | `industry_codes`: 47 個產業代碼清單；`stocks`: 2,405 支股票 → 所屬產業代碼對照 | 路由用、站內搜尋用、產業 ↔ 股票導覽 |
| `stocks_meta.json` | 每支股票的市場別代碼 (`m`)、中文簡稱、所屬產業 | 公司清單顯示名稱、串接後續財報 AJAX 端點 |
| `companies.json` | **2,405 家公司完整資料**：基本資料、財報（資產負債/損益/現金流）、經營理念、產品介紹、得獎紀錄、ESG、活動訊息、聯絡方式 | 公司頁主資料源（71 MB，建議按 stk 拆檔或塞 DB） |

### 📁 原始HTML_產業鏈/

47 個 `{產業代碼}.html`，櫃買中心原始介紹頁。內含完整的價值鏈視覺化 HTML/CSS 結構（`.chain-panel`、`.company-chain-panel`、箭頭定位等），若想直接照搬產業鏈圖的版型可以從這裡複製 markup。

### 📁 原始HTML_政府政策/

47 個 `{產業代碼}.html`，政府相關產業政策原始頁。`industries.json` 已抓出純文字版，若需要原始排版（標題、編號、超連結）就看這個。

## 產業代碼對照（部分）

```
1000 水泥          A100 半導體        C100 太陽能
2000 食品          A200 製藥          C200 風力發電
3000 石化及塑橡膠   A300 醫療器材       C300 LED照明
4100 紡織          B000 自動化         C400 電動車輛
5100-5800 各電子相關（PCB/被動元件/連接器/通信網路…）
D000 區塊鏈        F000 人工智慧       G000 雲端運算
H000 體驗科技      I000 金融科技       J000 大數據
K000 資通訊安全     M000 太空衛星      N000 食品生技
O000 再生醫療      P000 運動科技       … 等
```
完整代碼見 `結構化資料/codes.json`。

## industries.json 結構範例

```json
{
  "1000": {
    "ic": "1000",
    "intro": {
      "title": "水泥產業鏈簡介",
      "chain": {
        "上游": [{"code":"1100","name":"石灰石"}, ...],
        "中游": [{"code":"1500","name":"水泥生料"}, ...],
        "下游": [{"code":"1900","name":"營建業"}, ...]
      },
      "companies_by_segment": [
        [{"label":"本國上市公司(3家)", "companies":["台泥","幸福","信大"]}, ...]
      ]
    },
    "policy": {
      "title": "水泥相關產業政策",
      "text": "1.製造部門淨零轉型推動計畫..."
    }
  }
}
```

## 建站建議

1. **首頁 / 產業總覽** — 用 `codes.json` 的 47 個產業做 grid，每格連到 `/industry/{ic}`
2. **產業頁** — `/industry/{ic}` 從 `industries.json[ic]` 取資料：
   - 上方畫產業鏈圖（chain 三段）
   - 中間列出各區段對應的台灣上市公司、外國企業
   - 下方放政府政策全文 (policy.text)
3. **公司頁** — `/stock/{code}`：可從 `stocks_meta.json` 拿公司名與市場別，並 call AJAX 端點：
   - `https://dsp.tpex.org.tw/storage/company_basic/company_basic.php?s={stk}&m={m}` (JSONP) → 公司基本資料 + 財報
   - 公司理念 / 產品 / 得獎 / ESG / 活動：等下一波爬完會放進結構化 JSON
4. **搜尋** — 用 `codes.json.stocks` 與 `stocks_meta.json` 建 client-side 索引

## companies.json 結構範例（以 2330 台積電為例）

```json
{
  "2330": {
    "stk_code": "2330",
    "name": "台積電",
    "industry_code": "D000",
    "market_code": "22",
    "basic": {
      "COMPANY_NAME": "台灣積體電路製造股份有限公司",
      "ENGLISH_NAME": "Taiwan Semiconductor Manufacturing Co., Ltd.",
      "CHAIRMAN_NAME": "魏哲家", "PRESIDENT_NAME": "總裁: 魏哲家",
      "CAPITAL_AMT": "259325245210", "LISTING_DATE": "19940905",
      "COMPANY_TEL": "03-5636688", "INTERNET_ADDRESS": "https://www.tsmc.com",
      "COMPANY_ADDRESS": "新竹科學園區力行六路8號",
      "MAIN_BUSINESS1": "...", "MAIN_BUSINESS2": "...", ...
    },
    "finance": { /* 三大報表 */ },
    "contact": { "公司電話":"...", "公司網址":"...", ... },
    "vision_text": "...", "vision_story": "...",
    "csr": "...", "events": "...", "products": "...", "rewards": "..."
  }
}
```

## 補充說明

- `companies.json` 71 MB，前端不要直接載；建議：
  - **打包成 SQLite / Postgres** 後 API 提供
  - 或**按 stk_code 拆成 `/api/company/{stk}.json`** 個別小檔
- 所有資料來源屬櫃買中心公開資訊；商用發布前請確認授權條款
