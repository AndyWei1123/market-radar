# Fly.io 部署指南（保留自訂網域）

> 目標：把 Market Radar 部署到 Fly.io，網址用 `radar.twstockmap.com`。
> 預計時間：**45 分鐘**（含註冊）。
> 月費：**$0**（小流量在 $5 免費信用額度內）。

---

## 為什麼從 Streamlit Cloud 搬到 Fly.io？

| 比較 | Streamlit Cloud | Fly.io |
|---|---|---|
| 自訂網域 | ❌ 要 $250/月 | ✅ 免費 |
| 冷啟動 | 7 天睡 | ✅ 不睡 |
| RAM | 1 GB | 256MB ~ 512MB |
| 部署方式 | 連 GitHub auto | CLI / GitHub |
| 信用卡 | 不需要 | **需要綁卡** |

---

## Step 1：註冊 Fly.io（5 分鐘）

1. 打開 **https://fly.io/app/sign-up**
2. 選 **Sign up with GitHub**（用你的 AndyWei1123 帳號）
3. 進到 Dashboard → 它會要你 **Add payment method**
4. 填卡號（這一步不能跳過）。  
   👉 **不要擔心**：小型 dashboard 流量遠低於免費額度，月帳單會是 $0。  
   👉 萬一有意外開支，Fly.io 預設有 hard limit，不會無限燒錢。

## Step 2：裝 flyctl CLI（5 分鐘）

Mac terminal 跑：

```bash
curl -L https://fly.io/install.sh | sh
```

裝完它會提示加 `~/.fly/bin` 到 PATH。照它指示做，或重開 terminal。

驗證：

```bash
fly version
```

看到版號 = OK。

## Step 3：登入 + 部署（10 分鐘）

```bash
cd "/Users/andy/Desktop/claude code/market_radar"
fly auth login
```

瀏覽器跳出來 → 授權。回 terminal 看到 `successfully logged in` = OK。

```bash
fly launch --no-deploy
```

它會問幾個問題：

| 問題 | 怎麼答 |
|---|---|
| `Choose an app name` | 按 Enter 接受 `market-radar`（或自己取，要全域唯一） |
| `Choose a region` | 選 `nrt (Tokyo, Japan)` |
| `Would you like to set up Postgres?` | **No** |
| `Would you like to set up Upstash Redis?` | **No** |
| `Create .dockerignore from .gitignore?` | **No**（我們已有 .dockerignore） |

> 如果它說 fly.toml 已存在問要不要 overwrite → **選 No**（保留我寫好的版本）

完成後 deploy：

```bash
fly deploy
```

第一次 build 約 5~10 分鐘。看到 `1 desired, 1 placed, 1 healthy` = 成功 ✅

打開：

```bash
fly open
```

瀏覽器會打開你的 app（網址長 `https://market-radar.fly.dev`）。看得到 dashboard 就 OK。

## Step 4：綁自訂網域（10 分鐘）

### 4-1：跟 Fly.io 申請 SSL 憑證

```bash
fly certs add radar.twstockmap.com
```

它會吐出兩個 DNS 紀錄要你加，類似：

```
You can configure your DNS as follows:

CNAME radar.twstockmap.com -> market-radar.fly.dev

OR

A    radar.twstockmap.com   -> 66.241.124.123
AAAA radar.twstockmap.com   -> 2a09:8280:1::xx
```

### 4-2：到 Cloudflare 設 DNS

1. 登入 https://dash.cloudflare.com → `twstockmap.com` → **DNS** → **Records**
2. **先把舊的 `radar` CNAME 紀錄刪掉**（之前指向 streamlit.app 那筆）
3. 點 **Add record**，加：

| 欄位 | 填什麼 |
|---|---|
| Type | `CNAME` |
| Name | `radar` |
| Target | `market-radar.fly.dev` |
| **Proxy status** | ⚪ **DNS only**（**重要！這次是灰雲，不是橘雲**） |
| TTL | Auto |

> ⚠️ **為什麼是灰雲？** Fly.io 要直接看到訪客請求才能對其發 SSL。橘雲會擋在中間導致憑證簽不出來。

4. **Save**

### 4-3：等 SSL 簽發

回 terminal：

```bash
fly certs show radar.twstockmap.com
```

等 1~5 分鐘，狀態變成 `Configured = Yes` + `Certificate is configured to be issued` = 成功。

## Step 5：驗證 ✅

開**無痕視窗** → `https://radar.twstockmap.com/`

✅ 看到 dashboard、網址列保留 `radar.twstockmap.com`、SSL 鎖頭是綠色 → **大功告成**

---

## 之後的維護

### 程式有更新

本機改完 → push 到 GitHub → 在 terminal 跑：

```bash
fly deploy
```

5 分鐘內生效。

### 每日資料更新

跟之前一樣，本機跑：

```bash
python -m scripts.ingest_daily --incremental
python -m scripts.compute_themes
gzip -9 -k -f data/market.db
git add data/market.db.gz && git commit -m "data: $(date +%F)" && git push
fly deploy
```

### 看 logs

```bash
fly logs
```

### 進 container 偵錯

```bash
fly ssh console
```

---

## 帳單檢查（每月 1 號做一次）

```bash
fly orgs show personal
```

看 Current Usage。個人 dashboard 一般 $0~$1，不會超過免費信用 $5。

如果超過 $1 / 月，登入 dashboard 看哪個 VM 跑太多，可以縮 RAM 或停掉 backup VM。

---

## 常見問題

| 問題 | 解法 |
|---|---|
| `fly deploy` 失敗 build error | `fly logs` 看錯誤訊息 |
| 網址打開白屏 | `fly ssh console` 進去 `ls data/` 看 DB 有沒有解壓 |
| SSL 一直 pending | Cloudflare DNS 一定要是**灰雲**，橘雲會擋 |
| 502 Bad Gateway | App 還沒 boot 完，重整一次 |
| `out of memory` | 升 `memory = "1024mb"`（每月會多 $1~2） |

---

## 整理：跟 Streamlit Cloud 切換

部署到 Fly.io 後 Streamlit Cloud 那個 App 你可以：

- **保留**：當備援，Streamlit Cloud 後台 → Pause（不會被砍）
- **直接刪除**：徹底斷捨離，到 Streamlit Cloud → Settings → Delete app
