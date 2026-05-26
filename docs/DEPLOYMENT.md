# Market Radar 部署指南（免費方案）

> 給沒部署過網頁的人看的 step-by-step 指南。
> 預計花費：**首次 90 分鐘**，之後維護 0 分鐘（自動跑）。
> 花費：**$0 / 月**（網域選擇性 ~$10 / 年）。

---

## 為什麼不是純 Cloudflare Workers？

| 你以為的 | 實際上 |
|---|---|
| Cloudflare Workers 可以跑 Streamlit | ❌ Workers 是 JavaScript 邊緣運算，跑不了 Streamlit / pandas / yfinance |
| Cloudflare D1 = SQLite 可以無腦放 | ⚠️ D1 是雲端 SQLite 但不支援 Python 直連 |
| 一個平台搞定全部 | ❌ Cloudflare 沒有 Python web 託管服務 |

**真正可行的免費組合**（混合用，部分用 Cloudflare）：

| 服務 | 角色 | 費用 |
|---|---|---|
| **GitHub** | 放程式碼 + Actions 跑 cron | 免費 |
| **Streamlit Community Cloud** | 託管 Streamlit App 本體 | 免費（但休眠後冷啟動 30s） |
| **Cloudflare R2** | 放 SQLite DB 檔案 | 免費 10GB（夠用 5 年） |
| **Cloudflare DNS + Proxy** | 自訂網域 / CDN / DDoS 防護 | 免費（網域本身 ~$10/年） |
| **GitHub Actions** | 每日自動抓資料 + 重算指標 | 免費 2,000 分鐘/月 |

```
┌─────────────────────────────────────────────────────┐
│  瀏覽器 → marketradar.你的網域.com                    │
│            ↓                                          │
│  Cloudflare DNS / Proxy (CDN, 加速, SSL)             │
│            ↓                                          │
│  Streamlit Cloud 跑 Streamlit App                    │
│            ↓                                          │
│  讀 SQLite DB (從 Cloudflare R2 載下來)               │
└─────────────────────────────────────────────────────┘

每日 15:30 (台股收盤後):
  GitHub Actions cron
      ↓
  Python 跑 ingest_daily + compute_themes
      ↓
  把更新後的 market.db 上傳到 Cloudflare R2
      ↓
  Streamlit Cloud 自動重新讀檔
```

---

## Phase 0：事前準備（5 分鐘）

### 你需要的帳號（全部免費）

1. **GitHub** ── https://github.com/signup
2. **Streamlit Community Cloud** ── https://share.streamlit.io/signup（直接用 GitHub 登入）
3. **Cloudflare** ── https://dash.cloudflare.com/sign-up

帳號註冊完，先放著。

### 你電腦上需要的工具

只需要這兩個（如果都已經有就跳過）：

- **git** ── 用來 push 程式碼
  - Mac 已內建（terminal 打 `git --version` 驗證）
  - Windows 從 https://git-scm.com/download/win 下載安裝
- **GitHub Desktop**（GUI 版 git，**推薦無經驗者用這個**）
  - 下載 https://desktop.github.com/

---

## Phase 1：把程式碼上傳 GitHub（15 分鐘）

### 1.1 在 GitHub 建立新 repo

1. 登入 https://github.com → 右上角 `+` → **New repository**
2. 填：
   - **Repository name**: `market-radar`
   - **Description**: 「個人台股族群雷達」
   - **Public**（公開 ── 才能用 Streamlit Cloud 免費版）
   - ⚠️ **不要勾** Initialize with README（我們本機已經有檔案）
3. 點 **Create repository**

GitHub 會顯示一頁指令，先放著。

### 1.2 用 GitHub Desktop 推上去

1. 打開 GitHub Desktop → 登入你的 GitHub 帳號
2. **File** → **Add local repository** → 選擇資料夾：
   ```
   /Users/andy/Desktop/claude code/market_radar
   ```
3. 它會說「This directory does not appear to be a Git repository」→ 點 **create a repository**
4. 在彈窗：
   - Name: `market-radar`
   - **不要勾** Git LFS
   - 按 **Create repository**
5. 左下「Publish repository」→ **不要勾** "Keep this code private"（要 public）
6. 推上去。完成。

到 https://github.com/你的帳號/market-radar 看，應該看到全部檔案。

### 1.3 重要：先排除不該上傳的檔案

你的 repo 裡有些東西不該上傳（DB 檔太大、敏感資料）。在資料夾根目錄 create `.gitignore`（如果還沒有）：

```bash
# Python
__pycache__/
*.pyc
.venv/
venv/

# 本機資料庫（透過 R2 同步，不放 repo）
data/*.db
data/*.db-wal
data/*.db-shm

# 大檔案（companies.json 71MB）
tpex_ic_crawl/output/companies.json
tpex_ic_crawl/產業鏈網站素材/結構化資料/companies.json

# Streamlit 暫存
.streamlit/secrets.toml

# logs
logs/

# IDE
.vscode/
.idea/
.DS_Store
```

如果剛剛已經把 db 上傳到 repo，回 GitHub Desktop：
- 它會偵測到變更
- Commit message 寫「add .gitignore, remove db」
- Push

---

## Phase 2：設定 Cloudflare R2（放 DB 檔案，10 分鐘）

R2 = Cloudflare 的 S3。我們把 `data/market.db` 放這裡，App 啟動時下載。

### 2.1 啟用 R2

1. 登入 https://dash.cloudflare.com → 左側 **R2 Object Storage**
2. 第一次會要綁卡（驗證身分用，**不會扣款**，免費額度 10GB / 月）
3. 綁完點 **Create bucket**：
   - Name: `market-radar-db`
   - Location: `Asia-Pacific (APAC)`（離台灣近）
4. 建立完成 → 進入 bucket 頁

### 2.2 拿 R2 的 API 金鑰

1. R2 主頁 → 右上 **Manage R2 API Tokens**
2. **Create API token** → 填：
   - Token name: `market-radar-ci`
   - Permissions: **Object Read & Write**
   - Bucket: 只勾 `market-radar-db`
   - TTL: Forever
3. 按 **Create API Token**
4. **超重要**：跳出來會給你三個值：
   ```
   Access Key ID:     XXXXXXXXXXXXXXX
   Secret Access Key: YYYYYYYYYYYYYYYYYYY
   Endpoint:          https://xxxx.r2.cloudflarestorage.com
   ```
   ⚠️ 這頁關掉就再也看不到 Secret Key！馬上**複製到記事本**先存著。

### 2.3 手動先傳一次 DB 上去

最簡單的方法：用 R2 的網頁 UI 拖檔。

1. 進 `market-radar-db` bucket
2. 點 **Upload** → 上傳檔案
3. 選你電腦上的 `data/market.db`（約 70MB）
4. 等傳完。完成。

---

## Phase 3：改程式讓它從 R2 載 DB（20 分鐘）

我們要讓 Streamlit App 啟動時：「如果本機沒 DB，先從 R2 下載一份」。

### 3.1 加入下載 DB 的小程式

在專案根目錄建立檔案 `bootstrap_db.py`（用 GitHub Desktop 或文字編輯器都可）：

```python
"""啟動時從 Cloudflare R2 載 DB 到 data/market.db。"""
import os
from pathlib import Path
import boto3

DB_PATH = Path("data/market.db")
DB_PATH.parent.mkdir(exist_ok=True)

def download_db():
    if DB_PATH.exists() and DB_PATH.stat().st_size > 1_000_000:
        print(f"[bootstrap] DB 已存在 ({DB_PATH.stat().st_size//1024}KB), 跳過下載")
        return

    print("[bootstrap] 從 R2 下載 DB...")
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
        region_name="auto",
    )
    s3.download_file(
        Bucket=os.environ.get("R2_BUCKET", "market-radar-db"),
        Key="market.db",
        Filename=str(DB_PATH),
    )
    print(f"[bootstrap] ✅ 下載完成 ({DB_PATH.stat().st_size//1024}KB)")

if __name__ == "__main__":
    download_db()
```

把 `boto3` 加進 `requirements.txt`：

```
streamlit>=1.30
pandas
plotly
pyyaml
yfinance
requests
beautifulsoup4
boto3                  # ← 新增
```

### 3.2 在 Streamlit App 啟動時呼叫

編輯 `ui/app.py`，在最上方（`import streamlit as st` 後）加：

```python
# ─── 啟動時自動下載 DB ───
import sys
sys.path.insert(0, "..")
try:
    from bootstrap_db import download_db
    download_db()
except Exception as e:
    st.error(f"DB 下載失敗：{e}")
```

### 3.3 用 GitHub Desktop commit + push

回 GitHub Desktop：
- 左側會看到 `bootstrap_db.py` (新增) + `requirements.txt` (修改) + `ui/app.py` (修改)
- 下方 Summary: 「add R2 bootstrap」
- Commit to main → Push origin

---

## Phase 4：上 Streamlit Community Cloud（10 分鐘）

### 4.1 部署

1. 登入 https://share.streamlit.io（用 GitHub 帳號登入）
2. 點 **New app**
3. 選：
   - Repository: `你的帳號/market-radar`
   - Branch: `main`
   - Main file path: `ui/app.py`
   - App URL（可改）: `your-market-radar`
4. **進階設定** → 加 **Secrets**（這就是 R2 金鑰，放這裡比較安全）：

```toml
R2_ENDPOINT = "https://xxxx.r2.cloudflarestorage.com"
R2_ACCESS_KEY = "你的 Access Key"
R2_SECRET_KEY = "你的 Secret Key"
R2_BUCKET = "market-radar-db"
```

5. 按 **Deploy**！

等 3~5 分鐘第一次跑（安裝套件），然後你會拿到網址：
**`https://your-market-radar.streamlit.app`**

### 4.2 把 secrets 改成 Streamlit 能讀的格式

剛剛 secrets 用 toml 格式。但 `bootstrap_db.py` 是讀 `os.environ`，要再改一下讓 Streamlit secrets 注入到環境變數：

把 `bootstrap_db.py` 開頭改成：

```python
import os
from pathlib import Path
import boto3

# 讓 Streamlit secrets 注入 os.environ（本機用 env vars，雲端用 secrets）
try:
    import streamlit as st
    for k in ("R2_ENDPOINT", "R2_ACCESS_KEY", "R2_SECRET_KEY", "R2_BUCKET"):
        if k in st.secrets:
            os.environ[k] = st.secrets[k]
except (ImportError, FileNotFoundError):
    pass  # 本機沒裝 streamlit 或沒 secrets，跳過

DB_PATH = Path("data/market.db")
# ...（後面不變）
```

Commit + Push。Streamlit Cloud 會自動重新部署。

---

## Phase 5：設定 GitHub Actions 每日 cron（20 分鐘）

GitHub Actions 會每天台股收盤後（台北時間 15:30 = UTC 07:30）：
1. 跑 `ingest_daily.py` 抓今日股價
2. 跑 `compute_themes.py` 重算族群
3. 把新的 `market.db` 上傳到 R2

### 5.1 在 GitHub 設 Secrets

到 repo 頁 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

依序加 4 個：
- `R2_ENDPOINT` = `https://xxxx.r2.cloudflarestorage.com`
- `R2_ACCESS_KEY` = 你的 Access Key
- `R2_SECRET_KEY` = 你的 Secret Key
- `R2_BUCKET` = `market-radar-db`

### 5.2 建立 workflow 檔

在本機專案根建立 `.github/workflows/daily-update.yml`：

```yaml
name: Daily Market Data Update

on:
  schedule:
    # 每日 UTC 07:30 = 台北 15:30（台股收盤後 30 分鐘）
    - cron: "30 7 * * 1-5"   # 週一~週五
  workflow_dispatch:         # 允許手動觸發

jobs:
  ingest:
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install boto3

      - name: Download latest DB from R2
        env:
          R2_ENDPOINT: ${{ secrets.R2_ENDPOINT }}
          R2_ACCESS_KEY: ${{ secrets.R2_ACCESS_KEY }}
          R2_SECRET_KEY: ${{ secrets.R2_SECRET_KEY }}
          R2_BUCKET: ${{ secrets.R2_BUCKET }}
        run: python bootstrap_db.py

      - name: Run daily ingest
        run: python -m scripts.ingest_daily --incremental
        env:
          PYTHONPATH: .

      - name: Compute theme metrics
        run: python -m scripts.compute_themes
        env:
          PYTHONPATH: .

      - name: Upload updated DB to R2
        env:
          R2_ENDPOINT: ${{ secrets.R2_ENDPOINT }}
          R2_ACCESS_KEY: ${{ secrets.R2_ACCESS_KEY }}
          R2_SECRET_KEY: ${{ secrets.R2_SECRET_KEY }}
          R2_BUCKET: ${{ secrets.R2_BUCKET }}
        run: |
          python -c "
          import os, boto3
          s3 = boto3.client('s3',
              endpoint_url=os.environ['R2_ENDPOINT'],
              aws_access_key_id=os.environ['R2_ACCESS_KEY'],
              aws_secret_access_key=os.environ['R2_SECRET_KEY'],
              region_name='auto')
          s3.upload_file('data/market.db', os.environ['R2_BUCKET'], 'market.db')
          print('✅ Uploaded market.db to R2')
          "
```

Commit + Push。

### 5.3 手動測試一次

到 GitHub repo → **Actions** tab → 左側 **Daily Market Data Update** → 右側 **Run workflow** → **Run workflow**

等個 10 分鐘看綠燈 ✅。如果紅燈，點進去看哪步壞了。

### 5.4 讓 Streamlit Cloud 重新讀新 DB

預設 Streamlit Cloud 會 cache，DB 更新後不會立刻反映。兩種解法：

**簡單**：等 cache 過期（24 小時）
**好用**：在 `ui/_common.py` 的 cache 加 `ttl=300`（5 分鐘）── 你的程式碼已經有了。

或者，最乾淨的做法是改 `bootstrap_db.py` 加「checksum 比對」：
本機 DB 跟 R2 上的不同就重新下載。改進如下：

```python
def download_db():
    s3 = boto3.client("s3", ...)  # 略
    # 取 R2 的 ETag
    head = s3.head_object(Bucket=os.environ["R2_BUCKET"], Key="market.db")
    remote_etag = head["ETag"].strip('"')
    local_etag_file = DB_PATH.with_suffix(".etag")
    local_etag = local_etag_file.read_text() if local_etag_file.exists() else None

    if local_etag == remote_etag and DB_PATH.exists():
        print("[bootstrap] DB 是最新版，跳過下載")
        return

    print("[bootstrap] 下載新版 DB...")
    s3.download_file(os.environ["R2_BUCKET"], "market.db", str(DB_PATH))
    local_etag_file.write_text(remote_etag)
```

---

## Phase 6（選擇性）：綁自訂網域 + Cloudflare DNS（30 分鐘）

如果你想要 `marketradar.example.com` 而不是 `your-market-radar.streamlit.app`：

### 6.1 買網域

最便宜的：
- **Cloudflare Registrar**：成本價（.com ~$10/年），但要先有 Cloudflare 帳號
- **Namecheap / Porkbun**：類似價格

### 6.2 把網域 DNS 轉到 Cloudflare

1. Cloudflare dashboard → **Add a site** → 輸入你的網域
2. 選免費方案
3. Cloudflare 會給你 2 個 **Nameservers**（例：`alex.ns.cloudflare.com`）
4. 到你買網域的廠商，把 nameservers 改成 Cloudflare 給的兩個
5. 等 5~30 分鐘 DNS 生效

### 6.3 設 CNAME 指到 Streamlit App

回 Cloudflare → 你的網域 → **DNS** → **Add record**:
- Type: `CNAME`
- Name: `marketradar`（子網域）
- Target: `your-market-radar.streamlit.app`
- Proxy status: 🟠 **Proxied**（這樣才會走 Cloudflare CDN）

### 6.4 在 Streamlit Cloud 設 custom domain

Streamlit App → **Settings** → **Custom subdomain** → 輸入 `marketradar.example.com` → Save

等 5 分鐘，打開 `https://marketradar.example.com` 應該就看得到了。
（首次 SSL 簽發可能要 10 分鐘）

---

## 部署完之後

### ✅ 你會有的東西

- 公開網址 `https://你的子網域.streamlit.app`（或自訂網域）
- 每日台股 15:30 後自動更新資料
- Cloudflare 免費 CDN / DDoS 防護
- DB 集中在 R2，本機跟雲端共用同一份
- 30 秒冷啟動（沒人訪問 5 分鐘後會休眠）

### 🛠️ 常見維護操作

| 想做什麼 | 怎麼做 |
|---|---|
| 改 UI 文字 | 本機改完 → GitHub Desktop commit + push → Streamlit Cloud 1 分鐘內自動重部署 |
| 加新概念股 | 編 `config/taxonomy/tw/themes.yaml` → push → 等明天 cron 或手動觸發 GitHub Actions |
| 立刻更新資料 | GitHub → Actions → Run workflow（不用等到收盤後） |
| 暫停 App 省電 | Streamlit Cloud → App settings → Pause |
| 看 cron 跑得如何 | GitHub → Actions tab，每天會有一筆紀錄 |

### ⚠️ 注意事項

1. **冷啟動慢**：Streamlit Cloud 免費版閒置 7 天會徹底刪 container，第一個訪客要等 1 分鐘喚醒。可掛個 [Cron-job.org](https://cron-job.org) 每 5 分鐘 ping 一次保活（免費）。

2. **TWSE/TPEx 從美國 IP 抓資料**：GitHub Actions 跑在 US/EU，部分 TWSE 端點可能慢或被擋。如果發現法人 / 融資資料常失敗：
   - 暫時方案：cron 加 `--skip-flow` 跳過這些
   - 長期方案：在台灣的 server（Hetzner ARM 約 $4/月）跑 ingest，傳到 R2

3. **R2 免費額度**：10GB 儲存 + 每月 1,000 萬次讀。你的 DB 70MB，每日讀幾百次，**永遠用不完**。

4. **GitHub repo 容量**：因為 DB 放 R2，repo 自身大概 10MB，完全沒問題。

---

## TL;DR 心智圖

```
你（本機）─── GitHub Desktop ───┐
                                 ↓
                              GitHub repo ──┐
                                            │
                ┌───────────────────────────┤
                ↓                           ↓
        Streamlit Cloud             GitHub Actions (cron)
        (跑 App)                      ↓
                ↑                  yfinance / TWSE 抓資料
                │                     ↓
                └── 讀 DB ←── Cloudflare R2 ←── 寫 DB

加 Cloudflare DNS = 自訂網域 + CDN 加速
```

完成 Phase 1~5 你就有 **永久免費、自動更新** 的個人股票雷達網站。
