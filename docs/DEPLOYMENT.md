# 部署指南 — Streamlit Community Cloud + GitHub Actions 自動更新

> 目標：把 Market Radar 部署到 Streamlit Cloud，並設定每日自動更新資料。
> 時間：**首次 30 分鐘**，之後完全自動跑。
> 費用：**$0 / 月**。

---

## 架構

```
本機開發           GitHub                 Streamlit Cloud
─────────         ─────────             ──────────────────
你改程式碼   →   git push   →    自動重部署（1~2 分鐘）
                                          ↓
                                   xxx.streamlit.app（公開網址）

每日台北 16:00:
GitHub Actions cron 自動跑
   ↓ 抓股價 / 法人 / 新聞
   ↓ 重算族群指標
   ↓ 重壓 data/market.db.gz
   ↓ commit 回 main
Streamlit Cloud 偵測 → 自動重部署
```

---

## Phase 1：初次部署到 Streamlit Cloud（10 分鐘）

### 1.1 確認 repo 已 push 到 GitHub

repo 必須 **public**（免費版限制）。我們的已經是 `https://github.com/AndyWei1123/market-radar`。

### 1.2 部署

1. 打開 **https://share.streamlit.io**
2. **Sign in with GitHub**
3. 右上 **Create app**
4. 填：

| 欄位 | 填什麼 |
|---|---|
| Repository | `AndyWei1123/market-radar` |
| Branch | `main` |
| Main file path | `ui/app.py` |
| App URL | `market-radar`（或你喜歡的） |
| Python version | `3.11` |

5. 點 **Deploy!**

等 5~8 分鐘第一次跑（安裝套件 + 解壓 DB）。

### 1.3 把 App 改成 Public

⚠️ **超重要**：預設可能是 Private，外人看不到。

1. App 主頁右下 **Manage app**
2. **Settings** → **Sharing**
3. **App visibility** → **Public — anyone on the internet can view**
4. **Save**

驗證：用無痕視窗打 `https://你的app.streamlit.app/` 應該直接看到 dashboard，沒被導去登入頁。

---

## Phase 2：設定 GitHub Actions 每日自動更新（5 分鐘）

### 2.1 workflow 檔已就位

我們已經有 `.github/workflows/daily-update.yml`，每天台北 16:00 自動：

1. **抓今日股價**（yfinance，全球可用）
2. **抓三大法人 / 融資**（可能因 GitHub IP 被 TWSE 擋而失敗，但會繼續跑下一步）
3. **抓新聞**（多個 RSS 來源）
4. **重算族群指標 + 起漲狀態**
5. **重壓 `data/market.db.gz`**
6. **Commit 推回 GitHub main**
7. → Streamlit Cloud 偵測到 push → 自動重部署

### 2.2 開啟 Actions（如果還沒開的話）

1. 到 GitHub repo → **Actions** tab
2. 如果第一次進有提示 **「Workflows aren't being run on this fork」** 之類的，點 **Enable workflows**
3. 確認左側看得到 **每日資料更新** workflow

### 2.3 第一次手動測試

不要等到明天 16:00，現在就跑一次驗證沒問題：

1. **Actions** tab → 左側 **每日資料更新**
2. 右上 **Run workflow** → 下拉選 `main` branch → **Run workflow**
3. 等 5~15 分鐘
4. 看到綠勾 ✅ = 成功

### 2.4 看執行結果

點進去那次執行，看 **Summary** 區會有：

```markdown
## 📊 今日更新摘要
- 時間（台北）：2026-05-26 16:00
- DB 大小：27M
- 最新指標日期：2026-05-26
- 族群數：542
- 股票數：2150
```

如果某步驟失敗，紅叉旁邊點開看 log。

---

## Phase 3（選擇性）：保持 App 不冷啟動

Streamlit Cloud 免費版閒置 7 天會睡。掛免費保活：

1. 註冊 **https://cron-job.org**（免費）
2. **Create cronjob**：
   - URL: 你的 `https://xxx.streamlit.app/_stcore/health`
   - Schedule: **Every 5 minutes**
3. Save

---

## 維護手冊

### 我改了程式碼想看效果

```bash
# 本機開發完
git add -A
git commit -m "feat: 加了 XX 功能"
git push
# Streamlit Cloud 1~2 分鐘內自動重部署
```

### 我想立刻拉今天資料（不要等 cron）

GitHub repo → **Actions** → **每日資料更新** → **Run workflow**

### 我想加新概念股

```bash
# 編 config/taxonomy/tw/themes.yaml
git add config/taxonomy/tw/themes.yaml
git commit -m "feat: add XX theme"
git push
# 然後到 GitHub Actions Run workflow 重新算指標
```

### 我想看 cron 跑得如何

GitHub repo → **Actions** tab → 看每天的執行紀錄

### 我想暫停自動更新

GitHub repo → **Actions** → **每日資料更新** → 右上三個點 `⋯` → **Disable workflow**

---

## 常見問題

### Q1：Actions 失敗，紅叉
看 log 找 error 訊息。常見：
- **HTTP 403 / 連線拒絕** → TWSE 擋 GitHub IP，是已知問題，workflow 已加 `continue-on-error`，會跳過繼續
- **ModuleNotFoundError** → `requirements.txt` 漏裝套件，補上後 push
- **Disk space** → DB 太大，看是否有不該包進 .gz 的東西

### Q2：Streamlit Cloud 看到舊資料
- Streamlit Cloud cache 預設 24 小時，本程式設成 60 秒 (`@st.cache_data(ttl=60)`)
- 強制刷新：Streamlit App 右上漢堡選單 → **Rerun**
- 或重啟 App：Settings → **Reboot app**

### Q3：自動 commit 卡住沒 push
- 檢查 workflow 是否有 `permissions: contents: write`（我們已加）
- 或 repo Settings → Actions → Workflow permissions → 改成 **Read and write**

### Q4：cron 時區
- GitHub Actions cron 只認 UTC
- `0 8 * * 1-5` = UTC 08:00 = 台北 16:00 週一~五
- 如果想改時間，照 https://crontab.guru 算

---

## 下一步（之後再做）

- [ ] 加 Cloudflare DNS / Cloudflare R2 改善冷啟動（需要更多設定）
- [ ] 設定 Telegram / Email 推送：cron 跑完發訊息給自己
- [ ] 加 GitHub Actions matrix：把 TW / US 資料分開跑
- [ ] 切到付費 Streamlit Teams 拿到自訂網域功能
